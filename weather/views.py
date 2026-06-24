from datetime import timedelta

from django.shortcuts import render
from games.models import Game
from games.services.dates import eastern_today


def weather(request):
    today = eastern_today()
    day_param = request.GET.get("date", "today")
    if day_param == "yesterday":
        target_date = today - timedelta(days=1)
    elif day_param == "tomorrow":
        target_date = today + timedelta(days=1)
    else:
        day_param = "today"
        target_date = today

    games = Game.objects.select_related(
        "home_team", "away_team", "weather"
    ).filter(date=target_date).order_by("start_time_utc")

    game_weather = []
    for game in games:
        try:
            w = game.weather
            game_weather.append({
                "game": game,
                "rain_pct": w.rain_pct,
                "has_roof": w.has_roof,
                "wind_mph": w.wind_mph,
                "wind_dir": w.wind_dir,
                "wind_relative": w.wind_relative,
                "unknown": False,
            })
        except Exception:
            game_weather.append({
                "game": game,
                "rain_pct": None,
                "has_roof": False,
                "wind_mph": None,
                "wind_dir": None,
                "wind_relative": None,
                "unknown": True,
            })

    return render(request, "weather/weather.html", {
        "game_weather": game_weather,
        "selected_day": day_param,
        "target_date": target_date,
    })
