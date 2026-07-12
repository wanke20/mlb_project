import requests
from datetime import timedelta

from games.services.dates import eastern_today

BASE_URL = "https://statsapi.mlb.com/api/v1"

# Shared session so the many per-hitter split calls reuse pooled connections
# and load the CA bundle once, instead of a fresh TLS handshake per request.
# urllib3's pool is thread-safe; size it for the fetch_lineups thread pool.
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=32))

def get_schedule(game_date=None):
    if not game_date:
        game_date = eastern_today().strftime("%Y-%m-%d")

    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "probablePitcher,probablePitcher.stats(type=season,group=pitching)"
    }

    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def get_standings(season=2026):
    url = f"{BASE_URL}/standings"
    params = {
        "sportId": 1,
        "season": season,
        "leagueId": "103,104"  # AL and NL
    }

    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_teams(season=2026):
    """Return [{mlb_id, name, abbreviation}] for all MLB teams.

    Used to map a scraped lineup's team abbreviation to an MLBAM team id, since
    the stored Team.abbreviation is not reliably populated.
    """
    url = f"{BASE_URL}/teams"
    params = {"sportId": 1, "season": season}
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    return [
        {
            "mlb_id": t["id"],
            "name": t.get("name", ""),
            "abbreviation": t.get("abbreviation"),
        }
        for t in data.get("teams", [])
    ]


def get_team_season_hitting_stats(season=2026):
    """Return season hitting stats for all MLB teams as a dict keyed by team_id."""
    url = f"{BASE_URL}/teams/stats"
    params = {
        "stats": "season",
        "season": season,
        "group": "hitting",
        "sportId": 1,
    }
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    result = {}
    for split in data.get("stats", [{}])[0].get("splits", []):
        team_id = split.get("team", {}).get("id")
        stat = split.get("stat", {})
        if team_id:
            result[team_id] = {
                "avg": stat.get("avg"),
                "ops": stat.get("ops"),
                "runs": safe_int(stat.get("runs")),
                "strikeouts": safe_int(stat.get("strikeOuts")),
            }
    return result


def _get_team_hitting_last_days(days, season=2026):
    """Return hitting stats over the trailing ``days`` window for all MLB teams,
    keyed by team_id. ``days`` counts back inclusively from today."""
    end_date = eastern_today()
    start_date = end_date - timedelta(days=days - 1)
    url = f"{BASE_URL}/teams/stats"
    params = {
        "stats": "byDateRange",
        "season": season,
        "startDate": start_date.strftime("%m/%d/%Y"),
        "endDate": end_date.strftime("%m/%d/%Y"),
        "group": "hitting",
        "sportId": 1,
    }
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    result = {}
    for split in data.get("stats", [{}])[0].get("splits", []):
        team_id = split.get("team", {}).get("id")
        stat = split.get("stat", {})
        if team_id:
            result[team_id] = {
                "avg": stat.get("avg"),
                "ops": stat.get("ops"),
                "runs": safe_int(stat.get("runs")),
                "games": safe_int(stat.get("gamesPlayed")),
            }
    return result


def get_team_last7_hitting_stats(season=2026):
    """Return hitting stats for the last 7 days for all MLB teams, keyed by team_id."""
    return _get_team_hitting_last_days(7, season=season)


def get_team_last14_hitting_stats(season=2026):
    """Return hitting stats for the last 14 days for all MLB teams, keyed by team_id."""
    return _get_team_hitting_last_days(14, season=season)


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_team_reliever_stats(team_id, season=2026):
    """Return top relievers for a team sorted by season appearances."""
    url = f"{BASE_URL}/stats"
    params = {"stats": "season", "group": "pitching", "season": season, "teamId": team_id, "sportId": 1, "playerPool": "All", "limit": 40}
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    relievers = []
    for split in data.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        if (safe_int(stat.get("gamesStarted")) or 0) >= 3:
            continue
        appearances = safe_int(stat.get("gamesPitched")) or 0
        if appearances == 0:
            continue
        player = split.get("player", {})
        relievers.append({
            "mlb_id": player["id"],
            "name": player.get("fullName", ""),
            "appearances": appearances,
            "saves": safe_int(stat.get("saves")) or 0,
            "holds": safe_int(stat.get("holds")) or 0,
            "era": safe_float(stat.get("era")),
        })

    return sorted(relievers, key=lambda x: x["appearances"], reverse=True)


def get_game_result(game_id):
    """Return final score and starter earned runs from a completed game's boxscore."""
    url = f"{BASE_URL}/game/{game_id}/boxscore"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    def extract(side):
        team = data.get("teams", {}).get(side, {})
        runs = safe_int(team.get("teamStats", {}).get("batting", {}).get("runs"))
        pitcher_ids = team.get("pitchers", [])
        starter_er = None
        starter_ip = None
        if pitcher_ids:
            starter_key = f"ID{pitcher_ids[0]}"
            pitching = team.get("players", {}).get(starter_key, {}).get("stats", {}).get("pitching", {})
            starter_er = safe_int(pitching.get("earnedRuns"))
            starter_ip = pitching.get("inningsPitched")
        return runs, starter_er, starter_ip

    home_runs, home_er, home_ip = extract("home")
    away_runs, away_er, away_ip = extract("away")
    return {
        "home_score": home_runs,
        "away_score": away_runs,
        "home_starter_runs": home_er,
        "away_starter_runs": away_er,
        "home_starter_innings": home_ip,
        "away_starter_innings": away_ip,
    }


def get_game_pitchers(game_id):
    """Return {player_mlb_id: pitches_thrown} for all pitchers who appeared in a game."""
    url = f"{BASE_URL}/game/{game_id}/boxscore"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    result = {}
    for side in ("home", "away"):
        players = data.get("teams", {}).get(side, {}).get("players", {})
        for player_data in players.values():
            pitches = safe_int(player_data.get("stats", {}).get("pitching", {}).get("pitchesThrown"))
            if pitches:
                result[player_data["person"]["id"]] = pitches
    return result


def _innings_to_float(ip):
    """Convert MLB IP string ('12.1' = 12 1/3, '12.2' = 12 2/3) to a float."""
    if ip is None:
        return None
    try:
        ip = str(ip)
        whole, _, frac = ip.partition(".")
        whole_val = int(whole) if whole else 0
        frac_val = {"0": 0.0, "1": 1.0 / 3.0, "2": 2.0 / 3.0, "": 0.0}.get(frac)
        if frac_val is None:
            return float(ip)
        return whole_val + frac_val
    except (TypeError, ValueError):
        return None


# Approximate FanGraphs FIP constant — recalculated yearly to make league
# FIP equal league ERA. 3.15 is a reasonable mid-season estimate; relative
# pitcher comparisons are unaffected by small offsets.
FIP_CONSTANT = 3.15


def _compute_fip(stat):
    hr = safe_int(stat.get("homeRuns"))
    bb = safe_int(stat.get("baseOnBalls"))
    hbp = safe_int(stat.get("hitByPitch"))
    so = safe_int(stat.get("strikeOuts"))
    ip = _innings_to_float(stat.get("inningsPitched"))
    if None in (hr, bb, hbp, so) or not ip:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT, 2)


def _compute_k_bb_pct(stat):
    so = safe_int(stat.get("strikeOuts"))
    bb = safe_int(stat.get("baseOnBalls"))
    bf = safe_int(stat.get("battersFaced"))
    if None in (so, bb) or not bf:
        return None
    return round((so - bb) / bf * 100.0, 1)


EMPTY_PITCHER_STATS = {
    "throws": None,
    "era": None,
    "whip": None,
    "strikeouts": None,
    "walks": None,
    "innings_pitched": None,
    "fip": None,
    "k_bb_pct": None,
    # Opponent AVG / OPS against, by handedness and home/away, with batters
    # faced as the sample size.
    "vs_l_avg": None, "vs_l_ops": None, "vs_l_bf": None,
    "vs_r_avg": None, "vs_r_ops": None, "vs_r_bf": None,
    "home_avg": None, "home_ops": None, "home_bf": None,
    "away_avg": None, "away_ops": None, "away_bf": None,
}

# statSplit code -> the field prefix it populates on the pitcher record.
_PITCHER_SPLIT_CODES = {
    "vl": "vs_l",
    "vr": "vs_r",
    "h": "home",
    "a": "away",
}


def get_pitcher_stats(pitcher_id):
    year = 2026

    url = f"{BASE_URL}/people/{pitcher_id}"
    # Both stat types live in a SINGLE stats(...) hydration — the API rejects
    # two separate stats(...) hydrations. statSplits with sitCodes gives the
    # vs-LHB/RHB and home/away opponent lines in the same call as the season
    # line (see get_hitter_details for the analogous hitting query).
    params = {
        "hydrate": f"stats(group=pitching,type=[season,statSplits],sitCodes=[vl,vr,h,a],season={year})"
    }

    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()

    data = r.json()

    people = data.get("people", [])
    if not people:
        return dict(EMPTY_PITCHER_STATS)

    person = people[0]
    result = dict(EMPTY_PITCHER_STATS)
    result["throws"] = person.get("pitchHand", {}).get("code")

    for stat_group in person.get("stats", []):
        group_type = stat_group.get("type", {}).get("displayName")
        for split in stat_group.get("splits", []):
            code = split.get("split", {}).get("code")
            stat = split.get("stat", {})
            prefix = _PITCHER_SPLIT_CODES.get(code)
            if group_type == "statSplits" and prefix:
                result[f"{prefix}_avg"] = stat.get("avg")
                result[f"{prefix}_ops"] = stat.get("ops")
                result[f"{prefix}_bf"] = safe_int(stat.get("battersFaced"))
            elif group_type == "season":
                result["era"] = safe_float(stat.get("era"))
                result["whip"] = safe_float(stat.get("whip"))
                result["strikeouts"] = safe_int(stat.get("strikeOuts"))
                result["walks"] = safe_int(stat.get("baseOnBalls"))
                result["innings_pitched"] = stat.get("inningsPitched")
                result["fip"] = _compute_fip(stat)
                result["k_bb_pct"] = _compute_k_bb_pct(stat)

    return result


def get_team_roster(team_id, season=2026):
    """Return the team's players as [{mlb_id, name, bats}] for name->id resolution.

    Merges the active and 40-man rosters (deduped by id) so players on the
    40-man but not the active 26 (recent call-ups, pitchers between starts) are
    still resolvable. `bats` may be None if the API doesn't hydrate it; callers
    should treat it as a best-effort tiebreak only.
    """
    by_id = {}
    for roster_type in ("active", "40Man"):
        url = f"{BASE_URL}/teams/{team_id}/roster"
        params = {
            "rosterType": roster_type,
            "season": season,
            "hydrate": "person(batSide)",
        }
        try:
            r = _session.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue

        for entry in data.get("roster", []):
            person = entry.get("person", {})
            player_id = person.get("id")
            if not player_id or player_id in by_id:
                continue
            by_id[player_id] = {
                "mlb_id": player_id,
                "name": person.get("fullName", ""),
                "bats": person.get("batSide", {}).get("code"),
            }

    return list(by_id.values())


def get_team_top_hitters(team_id, season=2026, limit=6):
    """Return top hitters for a team by OPS, restricted to the team's PA leaders.

    Fetches the top 20 by plate appearances (to exclude bench/pitcher noise),
    then sorts those by OPS descending and returns the top `limit`.
    """
    url = f"{BASE_URL}/stats"
    params = {
        "stats": "season",
        "group": "hitting",
        "season": season,
        "teamId": team_id,
        "sportId": 1,
        "playerPool": "All",
        "sortStat": "plateAppearances",
        "order": "desc",
        "limit": 20,
    }
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    hitters = []
    for split in data.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        player = split.get("player", {})
        pa = safe_int(stat.get("plateAppearances")) or 0
        if pa < 30:
            continue
        hitters.append({
            "mlb_id": player["id"],
            "name": player.get("fullName", ""),
            "pa": pa,
            "avg": stat.get("avg"),
            "ops": stat.get("ops"),
        })

    hitters.sort(key=lambda h: safe_float(h["ops"]) or -1.0, reverse=True)
    return hitters[:limit]


EMPTY_HITTER_DETAILS = {
    "bats": None,
    "season_pa": None, "season_avg": None, "season_ops": None,
    "vs_l_pa": None, "vs_l_avg": None, "vs_l_ops": None,
    "vs_r_pa": None, "vs_r_avg": None, "vs_r_ops": None,
}


def get_hitter_details(player_id, season=2026):
    """Return handedness, season line, and vs-LHP/RHP splits for a hitter.

    One hydrated call to /people/{id} returns batSide, the season hitting line,
    and the two platoon splits. The season line lets the lineup fallback (which
    starts from a name, not the team stats leaderboard) populate the same
    season_* fields the top-6 path gets from get_team_top_hitters.
    """
    url = f"{BASE_URL}/people/{player_id}"
    # Both stat types must live in a SINGLE stats(...) hydration — the API
    # rejects two separate stats(...) hydrations ("provided multiple times
    # with different sub-hydrations").
    params = {
        "hydrate": f"stats(group=hitting,type=[season,statSplits],sitCodes=[vl,vr],season={season})"
    }
    r = _session.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    people = data.get("people", [])
    if not people:
        return dict(EMPTY_HITTER_DETAILS)

    person = people[0]
    result = dict(EMPTY_HITTER_DETAILS)
    result["bats"] = person.get("batSide", {}).get("code")

    for stat_group in person.get("stats", []):
        group_type = stat_group.get("type", {}).get("displayName")
        for split in stat_group.get("splits", []):
            code = split.get("split", {}).get("code")
            stat = split.get("stat", {})
            if code == "vl":
                result["vs_l_pa"] = safe_int(stat.get("plateAppearances"))
                result["vs_l_avg"] = stat.get("avg")
                result["vs_l_ops"] = stat.get("ops")
            elif code == "vr":
                result["vs_r_pa"] = safe_int(stat.get("plateAppearances"))
                result["vs_r_avg"] = stat.get("avg")
                result["vs_r_ops"] = stat.get("ops")
            elif group_type == "season":
                result["season_pa"] = safe_int(stat.get("plateAppearances"))
                result["season_avg"] = stat.get("avg")
                result["season_ops"] = stat.get("ops")

    return result
