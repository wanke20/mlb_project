"""Baseball Savant CSV leaderboards.

Two league-wide CSV pulls give us the Statcast subset of advanced metrics,
keyed by MLBAM ID for direct join against the Pitcher table.
"""
import csv
import io
import logging

import requests

logger = logging.getLogger(__name__)

EXPECTED_STATS_URL = "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
STATCAST_URL = "https://baseballsavant.mlb.com/leaderboard/statcast"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        f = float(value)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _fetch_csv(url, params):
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8-sig"  # strip BOM so the first header parses correctly
    return list(csv.DictReader(io.StringIO(r.text)))


def get_savant_leaderboard(year=2026):
    """Return {mlb_id: {woba, xwoba, xera, barrel_pct}} for every pitcher.

    Two HTTP calls total (both league-wide). Returns {} on failure so
    callers can degrade gracefully.
    """
    result = {}

    try:
        expected_rows = _fetch_csv(
            EXPECTED_STATS_URL,
            {"type": "pitcher", "year": year, "csv": "true", "minPA": 0},
        )
    except Exception as e:
        logger.error(f"Failed to fetch Savant expected_statistics: {e}")
        expected_rows = []

    for row in expected_rows:
        try:
            mlb_id = int(row["player_id"])
        except (KeyError, TypeError, ValueError):
            continue
        result[mlb_id] = {
            "woba": _to_float(row.get("woba")),
            "xwoba": _to_float(row.get("est_woba")),
            "xera": _to_float(row.get("xera")),
            "barrel_pct": None,
        }

    try:
        statcast_rows = _fetch_csv(
            STATCAST_URL,
            {"type": "pitcher", "year": year, "csv": "true"},
        )
    except Exception as e:
        logger.error(f"Failed to fetch Savant statcast leaderboard: {e}")
        statcast_rows = []

    for row in statcast_rows:
        try:
            mlb_id = int(row["player_id"])
        except (KeyError, TypeError, ValueError):
            continue
        record = result.setdefault(
            mlb_id, {"woba": None, "xwoba": None, "xera": None, "barrel_pct": None}
        )
        record["barrel_pct"] = _to_float(row.get("brl_percent"))

    return result
