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
        return {
            "era": None,
            "whip": None,
            "strikeouts": None,
            "walks": None,
            "innings_pitched": None,
        }

    stats = people[0].get("stats", [])

    if stats and stats[0].get("splits"):
        stat = stats[0]["splits"][0].get("stat", {})
        return {
            "era": safe_float(stat.get("era")),
            "whip": safe_float(stat.get("whip")),
            "strikeouts": safe_int(stat.get("strikeOuts")),
            "walks": safe_int(stat.get("baseOnBalls")),
            "innings_pitched": stat.get("inningsPitched"),
        }

    return {
        "era": None,
        "whip": None,
        "strikeouts": None,
        "walks": None,
        "innings_pitched": None,
    }
