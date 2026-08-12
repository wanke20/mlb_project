"""Projected-lineup scraping (RotoWire).

RotoWire publishes expected/confirmed daily lineups as plain server-rendered
HTML — no JS rendering, no Cloudflare wall (unlike Baseball Press, which 403s
non-browser requests). This module fetches and parses that page into plain
dicts; it does no DB work and resolves no ids. Name -> MLBAM id resolution is
the resolver's job (player_ids.py); turning lineups into DB rows is the
fetch_lineups command's job.

Returns {} on any failure so callers degrade gracefully to the existing
top-6 hitters / null starter behavior.
"""
import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ROTOWIRE_URL = "https://www.rotowire.com/baseball/daily-lineups.php"

# Each lineup box embeds its game's real calendar date in the links it carries
# (e.g. /baseball/box-score/...-2026-06-24-2941549). RotoWire's "today"/
# "tomorrow" params are relative to its own (US/Eastern) clock, which drifts
# from our UTC server date overnight, so we read this date and match on it
# rather than trusting the relative day we asked for.
_GAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})-\d{5,}")

# A browser-like UA is enough for RotoWire's lineup page; without it some
# responses are truncated.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Each odds row (LINE / O/U) carries a span per source. Prefer a real
# sportsbook when it's filled in, falling back to RotoWire's "composite"
# consensus, which is populated for every game. Order = preference.
_ODDS_SOURCE_PREFERENCE = ("draftkings", "fanduel", "betmgm", "pointsbet", "composite")

# The favorite's moneyline reads e.g. "DET -140" / "STL -2173".
_MONEYLINE_RE = re.compile(r"^([A-Za-z]{2,3})\s+([+-]?\d+)$")

# RotoWire only lists the favorite's moneyline. The underdog side is derived by
# assuming a standard two-way overround (implied probabilities sum to this),
# which reproduces a realistic vig-included underdog line rather than the naive
# fair complement. ~4.5% hold is typical for MLB moneylines.
_ML_OVERROUND = 1.045


def _clean(text):
    return " ".join(text.split()) if text else ""


def _american_to_prob(ml):
    """Vig-included implied probability of an American moneyline."""
    if ml < 0:
        return -ml / (-ml + 100.0)
    return 100.0 / (ml + 100.0)


def derive_underdog_moneyline(fav_ml):
    """Given the favorite's American moneyline (negative), return the underdog's
    derived American moneyline (positive), assuming a standard two-way vig.

    Returns None if the input can't yield a sensible underdog line.
    """
    if fav_ml is None or fav_ml >= 0:
        return None
    dog_prob = _ML_OVERROUND - _american_to_prob(fav_ml)
    if not 0 < dog_prob < 1:
        return None
    # Convert probability back to American odds. A near-pickem favorite can push
    # the derived underdog prob just above 0.5, which is a (small) negative line.
    if dog_prob > 0.5:
        return -round(100.0 * dog_prob / (1.0 - dog_prob))
    return round(100.0 * (1.0 - dog_prob) / dog_prob)


def fetch_projected_lineups(when="today", timeout=15):
    """Scrape RotoWire daily lineups for `when` in {"today", "tomorrow"}.

    Returns a dict keyed by uppercase team abbreviation:

        {
            "HOU": {
                "date": "2026-06-24" | None,   # the lineup's real game date
                "starter": "Peter Lambert" | None,
                "starter_hand": "R" | "L" | None,
                "status": "confirmed" | "expected" | None,
                # Favorite moneyline for this game (both teams in a box carry
                # the same pair). RotoWire only lists the favorite's line.
                "fav_abbr": "HOU" | None,      # favored team abbreviation
                "fav_moneyline": -140 | None,  # favorite's American odds
                "batters": [
                    {"order": 1, "pos": "SS", "name": "Jeremy Pena", "bats": "R"},
                    ...
                ],
            },
            ...
        }

    Returns {} on any network/parse failure.
    """
    params = {} if when == "today" else {"date": "tomorrow"}
    try:
        r = requests.get(ROTOWIRE_URL, params=params, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch RotoWire lineups ({when}): {e}")
        return {}

    try:
        return _parse_rotowire(r.text)
    except Exception as e:
        logger.error(f"Failed to parse RotoWire lineups ({when}): {e}")
        return {}


def _box_date(box):
    """The lineup box's real game date ("YYYY-MM-DD"), read from an embedded
    game link, or None if no dated link is present."""
    for a in box.select("a[href]"):
        m = _GAME_DATE_RE.search(a.get("href", ""))
        if m:
            return m.group(1)
    return None


def _parse_rotowire(html):
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    for box in soup.select("div.lineup__box"):
        abbrs = [_clean(a.get_text()) for a in box.select("div.lineup__teams div.lineup__abbr")]
        if len(abbrs) < 2:
            continue
        visit_abbr, home_abbr = abbrs[0], abbrs[1]
        box_date = _box_date(box)
        fav_abbr, fav_moneyline = _parse_odds(box)

        for abbr, selector in ((visit_abbr, "ul.lineup__list.is-visit"),
                               (home_abbr, "ul.lineup__list.is-home")):
            ul = box.select_one(selector)
            parsed = _parse_list(ul)
            if abbr and parsed:
                parsed["date"] = box_date
                parsed["fav_abbr"] = fav_abbr
                parsed["fav_moneyline"] = fav_moneyline
                result[abbr.upper()] = parsed

    return result


def _parse_odds(box):
    """Read the favorite's moneyline from a lineup box's odds block.

    Returns (fav_abbr, fav_moneyline) — e.g. ("DET", -140) — using the first
    populated source in _ODDS_SOURCE_PREFERENCE. Returns (None, None) if no
    moneyline is posted yet.
    """
    item = box.select_one("div.lineup__odds div.lineup__odds-item")
    if item is None:
        return None, None

    for source in _ODDS_SOURCE_PREFERENCE:
        span = item.select_one(f"span.{source}")
        if span is None:
            continue
        m = _MONEYLINE_RE.match(_clean(span.get_text()))
        if m:
            return m.group(1).upper(), int(m.group(2))

    return None, None


def _parse_list(ul):
    """Parse one team's <ul class="lineup__list"> into a lineup dict."""
    if ul is None:
        return None

    data = {"starter": None, "starter_hand": None, "status": None, "batters": []}

    highlight = ul.select_one("li.lineup__player-highlight")
    if highlight:
        name_el = highlight.select_one(".lineup__player-highlight-name a")
        if name_el:
            data["starter"] = name_el.get("title") or _clean(name_el.get_text()) or None
        throws_el = highlight.select_one(".lineup__throws")
        if throws_el:
            data["starter_hand"] = _clean(throws_el.get_text()) or None

    status_el = ul.select_one("li.lineup__status")
    if status_el:
        classes = status_el.get("class", [])
        if "is-confirmed" in classes:
            data["status"] = "confirmed"
        elif "is-expected" in classes:
            data["status"] = "expected"
        else:
            data["status"] = _clean(status_el.get_text()).lower() or None

    for order, li in enumerate(ul.select("li.lineup__player"), start=1):
        name_el = li.select_one("a")
        if name_el is None:
            continue
        name = name_el.get("title") or _clean(name_el.get_text())
        if not name:
            continue
        pos_el = li.select_one(".lineup__pos")
        bats_el = li.select_one(".lineup__bats")
        data["batters"].append({
            "order": order,
            "pos": _clean(pos_el.get_text()) if pos_el else None,
            "name": name,
            "bats": (_clean(bats_el.get_text()) or None) if bats_el else None,
        })

    return data
