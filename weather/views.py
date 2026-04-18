from django.shortcuts import render
from games.models import Game


def weather(request):
    games = Game.objects.select_related(
        "home_team", "away_team", "weather"
    ).order_by("start_time_utc")

    game_weather = []
    for game in games:
        try:
            w = game.weather
            game_weather.append({
                "game": game,
                "rain_pct": w.rain_pct,
                "has_roof": w.has_roof,
                "unknown": False,
            })
        except Exception:
            game_weather.append({
                "game": game,
                "rain_pct": None,
                "has_roof": False,
                "unknown": True,
            })

    return render(request, "weather/weather.html", {"game_weather": game_weather})
