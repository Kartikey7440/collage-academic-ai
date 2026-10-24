"""Password hashing and JWT token utilities.

Design decisions
----------------
- Passwords are hashed with bcrypt (via passlib).  The hash is stored in
  the ``users.password_hash`` column; plaintext never reaches the database.
- JWTs are signed with HS256 using a secret loaded from the environment.
  Two token types are issued:
    * access  — short-lived (default 30 min), sent with every API call.
    * refresh — long-lived (default 7 days), used only to obtain a new
      access token.
  The ``type`` claim distinguishes them so a refresh token cannot be used
  as an access token and vice-versa.
- All secrets and expiry durations come from environment variables so the
  values can differ between development, staging and production without
  touching code.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
from jose import JWTError, jwt

# ---------------------------------------------------------------------------
# Configuration (read once at module load)
# ---------------------------------------------------------------------------

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ---------------------------------------------------------------------------
# Password helpers  (bcrypt 4.x direct API — works on Python 3.13)
# ---------------------------------------------------------------------------


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of *plaintext* (rounds=12)."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if *plaintext* matches the stored bcrypt *hashed* value."""
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

TokenType = Literal["access", "refresh"]


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict | None = None,
) -> str:
    """Internal helper — build and sign a JWT.

    Parameters
    ----------
    subject:
        The ``sub`` claim; we use the user's integer ID as a string.
    token_type:
        ``"access"`` or ``"refresh"``.  Stored in the ``type`` claim so
        tokens cannot be mixed up.
    expires_delta:
        How long until the token expires.
    extra_claims:
        Optional additional claims merged into the payload (e.g. ``role``).
    """
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    """Return a signed access JWT for *user_id* with *role* as a claim."""
    return _create_token(
        subject=str(user_id),
        token_type="access",
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role},
    )


def create_refresh_token(user_id: int) -> str:
    """Return a signed refresh JWT for *user_id*."""
    return _create_token(
        subject=str(user_id),
        token_type="refresh",
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> dict:
    """Decode and validate *token*.

    Raises
    ------
    ValueError
        If the token is expired, has an invalid signature, or the ``type``
        claim does not match *expected_type*.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid or expired token: {exc}") from exc

    if payload.get("type") != expected_type:
        raise ValueError(
            f"Wrong token type: expected '{expected_type}', "
            f"got '{payload.get('type')}'"
        )
    return payload
