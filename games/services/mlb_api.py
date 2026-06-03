import requests
from datetime import date, timedelta

BASE_URL = "https://statsapi.mlb.com/api/v1"

def get_schedule(game_date=None):
    if not game_date:
        game_date = date.today().strftime("%Y-%m-%d")

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

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_team_season_hitting_stats(season=2026):
    """Return season hitting stats for all MLB teams as a dict keyed by team_id."""
    url = f"{BASE_URL}/teams/stats"
    params = {
        "stats": "season",
        "season": season,
        "group": "hitting",
        "sportId": 1,
    }
    r = requests.get(url, params=params, timeout=10)
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


def get_team_last7_hitting_stats(season=2026):
    """Return hitting stats for the last 7 days for all MLB teams, keyed by team_id."""
    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    url = f"{BASE_URL}/teams/stats"
    params = {
        "stats": "byDateRange",
        "season": season,
        "startDate": start_date.strftime("%m/%d/%Y"),
        "endDate": end_date.strftime("%m/%d/%Y"),
        "group": "hitting",
        "sportId": 1,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    result = {}
    for split in data.get("stats", [{}])[0].get("splits", []):
        team_id = split.get("team", {}).get("id")
        stat = split.get("stat", {})
        if team_id:
            result[team_id] = {
                "avg": stat.get("avg"),
                "runs": safe_int(stat.get("runs")),
            }
    return result


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
    r = requests.get(url, params=params, timeout=10)
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
}


def get_pitcher_stats(pitcher_id):
    year = 2026

    url = f"{BASE_URL}/people/{pitcher_id}"
    params = {
        "hydrate": f"stats(type=season,season={year},group=pitching)"
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()

    data = r.json()

    people = data.get("people", [])
    if not people:
        return dict(EMPTY_PITCHER_STATS)

    person = people[0]
    throws = person.get("pitchHand", {}).get("code")
    stats = person.get("stats", [])

    if stats and stats[0].get("splits"):
        stat = stats[0]["splits"][0].get("stat", {})
        return {
            "throws": throws,
            "era": safe_float(stat.get("era")),
            "whip": safe_float(stat.get("whip")),
            "strikeouts": safe_int(stat.get("strikeOuts")),
            "walks": safe_int(stat.get("baseOnBalls")),
            "innings_pitched": stat.get("inningsPitched"),
            "fip": _compute_fip(stat),
            "k_bb_pct": _compute_k_bb_pct(stat),
        }

    empty = dict(EMPTY_PITCHER_STATS)
    empty["throws"] = throws
    return empty


def get_team_top_hitters(team_id, season=2026, limit=4):
    """Return top hitters for a team by plate appearances.

    Returns a list of dicts with mlb_id, name, season pa/avg/ops. Pitchers and
    minor pinch-hit-only roles are filtered out via a PA floor.
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
    r = requests.get(url, params=params, timeout=10)
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
        if len(hitters) >= limit:
            break
    return hitters


EMPTY_HITTER_DETAILS = {
    "bats": None,
    "vs_l_pa": None, "vs_l_avg": None, "vs_l_ops": None,
    "vs_r_pa": None, "vs_r_avg": None, "vs_r_ops": None,
}


def get_hitter_details(player_id, season=2026):
    """Return handedness plus vs-LHP/RHP splits for a hitter.

    One hydrated call to /people/{id} returns both batSide and the two splits.
    """
    url = f"{BASE_URL}/people/{player_id}"
    params = {
        "hydrate": f"stats(group=hitting,type=statSplits,sitCodes=[vl,vr],season={season})"
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    people = data.get("people", [])
    if not people:
        return dict(EMPTY_HITTER_DETAILS)

    person = people[0]
    result = dict(EMPTY_HITTER_DETAILS)
    result["bats"] = person.get("batSide", {}).get("code")

    for stat_group in person.get("stats", []):
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

    return result
