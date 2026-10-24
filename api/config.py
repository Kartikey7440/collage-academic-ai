"""Central application configuration.

All tuneable values are read from environment variables (or .env) with
safe defaults. Import this module wherever you need a config value;
never read os.getenv() directly in business logic.

Timezone
--------
``COLLEGE_TIMEZONE`` controls every "what time is it now?" calculation in
the API — today's classes, next class, suppression check. Docker containers
default to UTC, so setting this correctly is critical for Indian deployments.

    COLLEGE_TIMEZONE=Asia/Kolkata   # IST — the default

Any IANA timezone string is accepted (e.g. "America/New_York").
"""

import os
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------

COLLEGE_TIMEZONE: str = os.getenv("COLLEGE_TIMEZONE", "Asia/Kolkata").strip("\"' ")

try:
    COLLEGE_TZ: tzinfo = ZoneInfo(COLLEGE_TIMEZONE)
except Exception:
    # Graceful fallback: If tzdata is missing or timezone lookup fails on Windows/Docker,
    # provide a fixed-offset timezone (UTC+5:30 for IST) so the app and tests never crash.
    if COLLEGE_TIMEZONE in ("Asia/Kolkata", "Asia/Calcutta", "IST"):
        COLLEGE_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")
    else:
        COLLEGE_TZ = timezone.utc


def now_college() -> datetime:
    """Return the current datetime in the college's local timezone.

    Use this **everywhere** you need 'now' — never call datetime.now() or
    datetime.utcnow() directly in business logic.
    """
    return datetime.now(COLLEGE_TZ)


# ---------------------------------------------------------------------------
# Security & JWT Auth
# ---------------------------------------------------------------------------

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-to-a-real-secret-before-deploying")
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL: str = os.getenv("DATABASE_URL", "")
DATABASE_URL_UNPOOLED: str = os.getenv("DATABASE_URL_UNPOOLED", "")


# ---------------------------------------------------------------------------
# Day helpers
# ---------------------------------------------------------------------------

#: Canonical mapping from 3-letter code to 0-based weekday int.
#: Consistent with Python's datetime.weekday() (0=Monday … 6=Sunday).
DAY_CODE_TO_INT: dict[str, int] = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}

#: Reverse mapping — used to turn a DB integer back into a human-readable name.
DAY_INT_TO_NAME: dict[int, str] = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday",
    3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday",
}
