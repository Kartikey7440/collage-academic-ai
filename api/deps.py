"""FastAPI dependency functions — the auth/identity layer.

The key export is ``get_current_identity``, which converts a Bearer token
into a ``ScopedIdentity`` object.  The scoped identity carries everything
the agent tools need to scope a query:

    branch_id, semester, section, batch  → for students
    faculty_id                           → for faculty
    user_id, role                        → for everyone

Scope is loaded from the database on every request, so changes (e.g. a
student moved to a different section) take effect immediately without
requiring a new token.

Usage in a route
----------------
    from api.deps import get_current_identity, ScopedIdentity, require_role

    @router.get("/me")
    async def me(identity: ScopedIdentity = Depends(get_current_identity)):
        return {"user_id": identity.user_id, "role": identity.role}

    @router.get("/admin-only")
    async def admin_only(
        identity: ScopedIdentity = Depends(require_role("admin"))
    ):
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.security import decode_token
from db.models import FacultyUser, Student, User, UserRole
from db.session import AsyncSessionLocal

# FastAPI will extract the Bearer token from the Authorization header (or None if missing).
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Scoped identity dataclass
# ---------------------------------------------------------------------------


@dataclass
class ScopedIdentity:
    """Immutable snapshot of who is making the request and their academic scope.

    Attributes
    ----------
    user_id : int
        Primary key of the ``users`` row.
    role : str
        One of ``"admin"``, ``"faculty"``, ``"student"``.

    Student-only (None for admin/faculty)
    --------------
    student_id : int | None
    branch_id  : int | None
    semester   : int | None
    section    : str | None
    batch      : str | None
    roll_no    : str | None

    Faculty-only (None for admin/student)
    -------------
    faculty_id : int | None
        The ``faculty.id`` (reference table), not the user id.
    """

    user_id: int
    role: str

    # Student scope
    student_id: Optional[int] = field(default=None)
    branch_id: Optional[int] = field(default=None)
    semester: Optional[int] = field(default=None)
    section: Optional[str] = field(default=None)
    batch: Optional[str] = field(default=None)
    roll_no: Optional[str] = field(default=None)

    # Faculty scope
    faculty_id: Optional[int] = field(default=None)

    # ------------------------------------------------------------------ #
    # Convenience guards used in route handlers                           #
    # ------------------------------------------------------------------ #

    def is_student(self) -> bool:
        return self.role == UserRole.student.value

    def is_faculty(self) -> bool:
        return self.role == UserRole.faculty.value

    def is_admin(self) -> bool:
        return self.role == UserRole.admin.value


# ---------------------------------------------------------------------------
# DB session dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncSession:  # type: ignore[return]
    """Yield a single async session, auto-committed or rolled back."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Core identity dependency
# ---------------------------------------------------------------------------


async def get_current_identity(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ScopedIdentity:
    """Validate the Bearer token and return a fully-scoped identity.

    Raises HTTP 401 on any token problem (missing, expired, wrong type).
    Raises HTTP 401 if the user row no longer exists in the database.
    """
    _cred_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise _cred_error

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except ValueError:
        raise _cred_error

    user_id_str: str = payload.get("sub", "")
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise _cred_error

    # Load the user and all profile relationships in one round-trip.
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.student_profile).selectinload(Student.branch),
            selectinload(User.faculty_profile).selectinload(FacultyUser.faculty),
        )
    )
    result = await db.execute(stmt)
    user: Optional[User] = result.scalars().first()

    if user is None:
        raise _cred_error

    # Build the scoped identity based on role.
    identity = ScopedIdentity(user_id=user.id, role=user.role.value)

    if user.role == UserRole.student and user.student_profile:
        sp = user.student_profile
        identity.student_id = sp.id
        identity.branch_id = sp.branch_id
        identity.semester = sp.semester
        identity.section = sp.section
        identity.batch = sp.batch
        identity.roll_no = sp.roll_no

    elif user.role == UserRole.faculty and user.faculty_profile:
        identity.faculty_id = user.faculty_profile.faculty_id

    return identity


# ---------------------------------------------------------------------------
# Role-gating helper
# ---------------------------------------------------------------------------


def require_role(*roles: str) -> Callable:
    """Return a dependency that raises HTTP 403 unless the caller has one of *roles*.

    Usage::

        @router.delete("/admin/users/{uid}")
        async def delete_user(
            identity: ScopedIdentity = Depends(require_role("admin"))
        ):
            ...
    """

    async def _check(
        identity: ScopedIdentity = Depends(get_current_identity),
    ) -> ScopedIdentity:
        if identity.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to: {', '.join(roles)}.",
            )
        return identity

    return _check
