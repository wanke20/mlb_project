import requests
from datetime import date

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


def get_standings(season=2025):
    url = f"{BASE_URL}/standings"
    params = {
        "sportId": 1,
        "season": season,
        "leagueId": "103,104"  # AL and NL
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


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
    year = 2025

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
