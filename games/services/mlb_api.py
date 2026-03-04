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


def get_pitcher_era(pitcher_id):
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
        return None

    stats = people[0].get("stats", [])

    if stats and stats[0].get("splits"):
        try:
            return float(stats[0]["splits"][0]["stat"]["era"])
        except (KeyError, ValueError, IndexError):
            return None

    return None