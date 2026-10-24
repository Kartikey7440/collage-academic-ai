"""Auth router — signup, login, and token refresh.

Endpoints
---------
POST /auth/signup   Create a new student or faculty account.
POST /auth/login    Exchange email + password for an access/refresh token pair.
POST /auth/refresh  Exchange a valid refresh token for a new access token.

Design notes
------------
- Admin accounts are not created through this endpoint; they are seeded
  directly in the database.  The signup endpoint rejects role="admin".
- For students, branch_code, semester, roll_no are required fields.
  section and batch are optional (matching the MITS timetable structure).
- For faculty, faculty_code must match an existing row in the faculty
  reference table.  This prevents creating ghost faculty logins.
- All password verification is constant-time (via passlib).
- Token expiry values come from environment variables, not hardcoded.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_identity, ScopedIdentity
from api.schemas import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)
from api.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from db.models import Branch, Faculty, FacultyUser, Student, User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /auth/signup
# ---------------------------------------------------------------------------


@router.post(
    "/signup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new student or faculty account",
)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Create a new user account and return a token pair.

    Validates:
    - Email is unique.
    - Role is 'student' or 'faculty' (admin not allowed via this endpoint).
    - Student fields (roll_no, branch_code, semester) are provided for students.
    - faculty_code exists in the faculty reference table for faculty.
    """
    # Guard: admins cannot self-register
    if body.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts cannot be created via signup.",
        )

    # Validate role-specific required fields
    if body.role == "student":
        missing = [f for f in ("roll_no", "branch_code", "semester") if not getattr(body, f)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Students must provide: {', '.join(missing)}.",
            )
    elif body.role == "faculty":
        if not body.faculty_code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Faculty must provide faculty_code.",
            )

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    # Create the user row
    role_enum = UserRole.student if body.role == "student" else UserRole.faculty
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=role_enum,
    )
    db.add(user)
    await db.flush()  # Assign user.id without committing yet

    # Create the profile row
    if body.role == "student":
        branch = await _resolve_branch(db, body.branch_code)
        profile = Student(
            user_id=user.id,
            branch_id=branch.id,
            semester=body.semester,
            section=body.section,
            batch=body.batch,
            roll_no=body.roll_no,
        )
        db.add(profile)

    elif body.role == "faculty":
        faculty_ref = await _resolve_faculty_code(db, body.faculty_code)
        # Check the faculty code isn't already linked to another login
        existing_link = await db.execute(
            select(FacultyUser).where(FacultyUser.faculty_id == faculty_ref.id)
        )
        if existing_link.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Faculty code '{body.faculty_code}' is already linked to an account.",
            )
        link = FacultyUser(user_id=user.id, faculty_id=faculty_ref.id)
        db.add(link)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account creation failed due to a conflict. Please try again.",
        )

    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Exchange credentials for an access/refresh token pair",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Authenticate with email + password and return a token pair."""
    result = await db.execute(select(User).where(User.email == body.email))
    user: Optional[User] = result.scalars().first()

    # Use the same generic message for both "no user" and "wrong password"
    # to avoid leaking which emails are registered.
    _bad = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None or not verify_password(body.password, user.password_hash):
        raise _bad

    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    """Issue a new access token from a valid refresh token.

    The refresh token is validated (signature, expiry, type claim).
    The user row is re-fetched so a deleted account cannot keep refreshing.
    """
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user: Optional[User] = result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AccessTokenResponse(
        access_token=create_access_token(user.id, user.role.value)
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the authenticated user's public profile",
)
async def me(
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Return basic user info.  Requires a valid access token."""
    result = await db.execute(select(User).where(User.id == identity.user_id))
    user: Optional[User] = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserOut.model_validate(user)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _resolve_branch(db: AsyncSession, code: Optional[str]) -> Branch:
    """Return the Branch for *code*, or raise 422 if it does not exist."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="branch_code is required for students.",
        )
    result = await db.execute(select(Branch).where(Branch.code == code.upper()))
    branch: Optional[Branch] = result.scalars().first()
    if branch is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Branch code '{code}' not found.  It must be created by an admin first.",
        )
    return branch


async def _resolve_faculty_code(db: AsyncSession, code: Optional[str]) -> Faculty:
    """Return the Faculty reference row for *code*, or raise 422."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="faculty_code is required for faculty accounts.",
        )
    result = await db.execute(select(Faculty).where(Faculty.code == code.upper()))
    faculty: Optional[Faculty] = result.scalars().first()
    if faculty is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Faculty code '{code}' not found in the reference table.  "
                "Ask an admin to add it before creating your account."
            ),
        )
    return faculty
