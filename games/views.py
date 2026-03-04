import io
import base64
import numpy as np
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from django.shortcuts import render, get_object_or_404
from scipy.stats import norm
from django.http import JsonResponse
from .models import Game
from games.services.prediction import predict_game


def game_list(request):
    games = Game.objects.select_related(
        "home_team", "away_team", "home_pitcher", "away_pitcher"
    )

    context = {
        "games": games
    }

    return render(request, "games/game_list.html", context)


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

    # ------------------------
    # Logit-Normal (Win Prob)
    # ------------------------
    mean_p = prediction["win_probability"]

    # Convert to logit space
    logit_mean = np.log(mean_p / (1 - mean_p))
    sigma_logit = 0.6  # tune this later via calibration

    x = np.linspace(0.001, 0.999, 500)
    logit_x = np.log(x / (1 - x))
    y = norm.pdf(logit_x, logit_mean, sigma_logit) / (x * (1 - x))

    plt.figure()
    plt.plot(x, y)
    plt.title("Logit-Normal Win Probability Distribution")
    plt.xlabel(f"Home Win Probability ({game.home_team.name})")
    plt.ylabel("Density")

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    win_image = base64.b64encode(buf.getvalue()).decode("utf-8")

    # ------------------------
    # Normal Run Distribution
    # ------------------------
    mu = prediction["expected_run_diff"]
    sigma_runs = 2.5

    x2 = np.linspace(mu - 4*sigma_runs, mu + 4*sigma_runs, 400)
    y2 = norm.pdf(x2, mu, sigma_runs)

    plt.figure()
    plt.plot(x2, y2)
    plt.title("Run Differential Distribution")
    plt.xlabel("Run Differential (Home - Away)")
    plt.ylabel("Density")

    buf2 = io.BytesIO()
    plt.savefig(buf2, format="png")
    plt.close()
    buf2.seek(0)
    run_image = base64.b64encode(buf2.getvalue()).decode("utf-8")

    context = {
        "game": game,
        "win_image": win_image,
        "run_image": run_image,
        "prediction": prediction,
    }

    return render(request, "games/prediction.html", context)