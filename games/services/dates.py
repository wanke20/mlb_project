"""Shared date helpers.

The app's "day" should follow the US/Eastern baseball calendar, not the UTC
server clock. The MLB schedule's official game date is Eastern-based, and that
is what we store in ``Game.date``. Deriving "today" from a UTC clock (the
deploy and GitHub Actions both run UTC) drifts a day ahead overnight: any time
after ~8pm ET it is already tomorrow in UTC, so the app would jump to the next
day's slate — and the lineup/weather fetches would label data with the wrong
date. Compute "today" in Eastern everywhere a day boundary matters.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def eastern_today():
    """Today's date on the US/Eastern baseball calendar."""
    return datetime.now(EASTERN).date()
