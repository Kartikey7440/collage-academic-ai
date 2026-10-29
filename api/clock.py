"""One source of "now" for the whole API, with an optional demo clock.

Normal use: ``current_now()`` is the real college time (``api.config.now_college``).

Demo use: put ``DEMO_NOW=2026-11-03T11:30`` in ``.env`` (college local time).
The API then behaves as if it were that moment when the server started, and the
clock keeps ticking from there. Remove the line to go back to real time.
Restarting the server (including an auto-reload) restarts the demo clock.
"""

import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from api.config import now_college

load_dotenv()

_real_start = now_college()
_demo_start: Optional[datetime] = None

_raw = os.environ.get("DEMO_NOW", "").strip()
if _raw:
    _parsed = datetime.fromisoformat(_raw)
    if _parsed.tzinfo is None:
        _parsed = _parsed.replace(tzinfo=_real_start.tzinfo)
    _demo_start = _parsed


def current_now() -> datetime:
    """The college's current date and time (or the demo clock if DEMO_NOW is set)."""
    if _demo_start is None:
        return now_college()
    return _demo_start + (now_college() - _real_start)


def demo_clock_active() -> bool:
    return _demo_start is not None