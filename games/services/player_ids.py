"""Name -> MLBAM id resolution for projected-lineup sources.

Projected lineups (RotoWire, Baseball Press) give player names, not MLBAM ids,
but the rest of the pipeline is keyed on `mlb_id`. This module resolves a name
(possibly with an abbreviated first name, e.g. "Y. Alvarez") against the team's
roster and caches the result in `PlayerIDMap` so the fuzzy match and the roster
API call only happen the first time a player is seen.

Source-agnostic: the same resolver serves the starter fallback and the hitter
fallback, regardless of which projected source produced the name.
"""
import unicodedata

from games.models import PlayerIDMap
from games.services.mlb_api import get_team_roster

# Generational suffixes are dropped during normalization so "Vladimir
# Guerrero Jr." and a source that omits the suffix still match.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name):
    """Lowercase, strip accents/punctuation, and drop suffixes for matching."""
    if not name:
        return ""
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    ascii_name = ascii_name.lower().replace(".", " ").replace("-", " ")
    parts = [p for p in ascii_name.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


def _last_name(normalized):
    parts = normalized.split()
    return parts[-1] if parts else ""


def _first_initial(normalized):
    parts = normalized.split()
    return parts[0][0] if parts and parts[0] else ""


def _match_in_roster(normalized, bats, roster):
    """Best-effort match of a normalized name against roster candidates.

    Strategy, most-specific first:
      1. exact normalized full-name match (unique)
      2. last-name match (unique)
      3. last-name + first-initial match (unique)  -- handles "Y. Alvarez"
      4. ...still tied -> disambiguate by batting hand, if provided

    Returns a roster dict or None if no confident match exists.
    """
    candidates = [
        {**c, "_norm": normalize_name(c["name"])} for c in roster
    ]

    exact = [c for c in candidates if c["_norm"] == normalized]
    if len(exact) == 1:
        return exact[0]

    last = _last_name(normalized)
    by_last = [c for c in candidates if _last_name(c["_norm"]) == last]
    if len(by_last) == 1:
        return by_last[0]
    if not by_last:
        return None

    initial = _first_initial(normalized)
    by_initial = [c for c in by_last if _first_initial(c["_norm"]) == initial]
    if len(by_initial) == 1:
        return by_initial[0]

    pool = by_initial or by_last
    if bats:
        by_bats = [c for c in pool if c.get("bats") == bats]
        if len(by_bats) == 1:
            return by_bats[0]

    return None


def resolve_player_id(name, team, bats=None, season=2026, _roster=None):
    """Resolve a player name to an MLBAM id for `team`, caching the result.

    Returns the int mlb_id, or None if no confident match is found. Pass
    `_roster` to reuse an already-fetched roster across many lookups (see
    `resolve_players`).
    """
    normalized = normalize_name(name)
    if not normalized:
        return None

    cached = PlayerIDMap.objects.filter(
        normalized_name=normalized, team=team
    ).first()
    if cached:
        return cached.mlb_id

    roster = _roster if _roster is not None else get_team_roster(team.mlb_id, season)
    match = _match_in_roster(normalized, bats, roster)
    if not match:
        return None

    PlayerIDMap.objects.update_or_create(
        normalized_name=normalized,
        team=team,
        defaults={
            "name": name,
            "mlb_id": match["mlb_id"],
            "bats": bats or match.get("bats"),
        },
    )
    return match["mlb_id"]


def resolve_players(entries, team, season=2026):
    """Resolve a lineup for one team, hitting the roster only for cache misses.

    Every name is looked up in PlayerIDMap first (one query for the whole
    team). The team roster is fetched at most once, and only if some name isn't
    cached yet — so a fully warm cache makes zero roster calls.

    `entries` is an iterable of dicts with at least a "name" key and an optional
    "bats" key. Returns a list of {**entry, "mlb_id": int|None} preserving order.
    """
    entries = list(entries)
    if not entries:
        return []

    cache = {
        p.normalized_name: p.mlb_id
        for p in PlayerIDMap.objects.filter(team=team)
    }

    results = []
    misses = []  # (index into results, entry) for names not in the cache
    for entry in entries:
        mlb_id = cache.get(normalize_name(entry.get("name")))
        results.append({**entry, "mlb_id": mlb_id})
        if mlb_id is None:
            misses.append((len(results) - 1, entry))

    if misses:
        roster = get_team_roster(team.mlb_id, season)
        for idx, entry in misses:
            results[idx]["mlb_id"] = resolve_player_id(
                entry.get("name"),
                team,
                bats=entry.get("bats"),
                season=season,
                _roster=roster,
            )

    return results
