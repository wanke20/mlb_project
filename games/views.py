import json
import math
from statistics import NormalDist

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.db.models import F
from .models import Game, Team
from games.services.prediction import predict_game


def _linspace(start, stop, n):
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


def home_page(request):
    return render(request, "games/home.html")


def trends(request):
    teams = Team.objects.filter(wins__isnull=False).order_by("-wins", "losses")
    return render(request, "games/trends.html", {"teams": teams})


def game_list(request):
    games = Game.objects.select_related(
        "home_team", "away_team", "home_pitcher", "away_pitcher"
    ).order_by(F("start_time_utc").asc(nulls_last=True), "game_id")
    return render(request, "games/game_list.html", {"games": games})


def game_prediction(request, game_id):
    game = get_object_or_404(
        Game.objects.select_related(
            "home_team", "away_team", "home_pitcher", "away_pitcher"
        ),
        game_id=game_id,
    )

    prediction = predict_game(
        game.home_team,
        game.away_team,
        game.home_pitcher,
        game.away_pitcher,
    )

    # Win probability — logit-normal density
    mean_p = prediction["win_probability"]
    logit_mean = math.log(mean_p / (1 - mean_p))
    sigma_logit = 0.6
    logit_dist = NormalDist(logit_mean, sigma_logit)
    x_win = _linspace(0.001, 0.999, 200)
    y_win = [logit_dist.pdf(math.log(x / (1 - x))) / (x * (1 - x)) for x in x_win]

    # Run differential — normal density
    mu = prediction["expected_run_diff"]
    sigma_runs = 2.5
    run_dist = NormalDist(mu, sigma_runs)
    x_run = _linspace(mu - 4 * sigma_runs, mu + 4 * sigma_runs, 200)
    y_run = [run_dist.pdf(x) for x in x_run]

    # Run total — normal density
    mu_total = prediction["expected_total"]
    sigma_total = 3.0
    total_dist = NormalDist(mu_total, sigma_total)
    x_total = _linspace(mu_total - 4 * sigma_total, mu_total + 4 * sigma_total, 200)
    y_total = [total_dist.pdf(x) for x in x_total]

    def chart_json(xs, ys):
        return json.dumps([{"x": round(x, 4), "y": round(y, 4)} for x, y in zip(xs, ys)])

    context = {
        "game": game,
        "prediction": prediction,
        "win_chart": chart_json(x_win, y_win),
        "run_chart": chart_json(x_run, y_run),
        "total_chart": chart_json(x_total, y_total),
    }

    return render(request, "games/prediction.html", context)
