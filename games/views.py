import io
import base64
import numpy as np
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from django.shortcuts import render, get_object_or_404
from scipy.stats import norm
from django.http import JsonResponse
from django.db.models import F
from .models import Game, Team
from games.services.prediction import predict_game

def home_page(request):
    return render(request, "games/home.html")


def trends(request):
    teams = Team.objects.filter(wins__isnull=False).order_by("-wins", "losses")
    return render(request, "games/trends.html", {"teams": teams})


def game_list(request):
    games = Game.objects.select_related(
        "home_team", "away_team", "home_pitcher", "away_pitcher"
    ).order_by(F("start_time_utc").asc(nulls_last=True), "game_id")

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

    BG      = "#161b22"
    SURFACE = "#0d1117"
    TEXT    = "#e6edf3"
    MUTED   = "#8b949e"
    ACCENT  = "#58a6ff"
    GRID    = "#30363d"

    def apply_dark(ax, fig):
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(SURFACE)
        ax.tick_params(colors=MUTED, labelsize=9)
        ax.xaxis.label.set_color(MUTED)
        ax.yaxis.label.set_color(MUTED)
        ax.title.set_color(TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(True, color=GRID, linewidth=0.5, linestyle="--", alpha=0.6)

    # ------------------------
    # Logit-Normal (Win Prob)
    # ------------------------
    mean_p = prediction["win_probability"]

    logit_mean = np.log(mean_p / (1 - mean_p))
    sigma_logit = 0.6  # tune this later via calibration

    x = np.linspace(0.001, 0.999, 500)
    logit_x = np.log(x / (1 - x))
    y = norm.pdf(logit_x, logit_mean, sigma_logit) / (x * (1 - x))

    fig, ax = plt.subplots()
    ax.plot(x, y, color=ACCENT, linewidth=1.8)
    ax.set_title("Win Probability Distribution")
    ax.set_xlabel(f"Home Win Probability ({game.home_team.name})")
    ax.set_ylabel("Density")
    apply_dark(ax, fig)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    win_image = base64.b64encode(buf.getvalue()).decode("utf-8")

    # ------------------------
    # Normal Run Distribution
    # ------------------------
    mu = prediction["expected_run_diff"]
    sigma_runs = 2.5

    x2 = np.linspace(mu - 4*sigma_runs, mu + 4*sigma_runs, 400)
    y2 = norm.pdf(x2, mu, sigma_runs)

    fig2, ax2 = plt.subplots()
    ax2.plot(x2, y2, color=ACCENT, linewidth=1.8)
    ax2.set_title("Run Differential Distribution")
    ax2.set_xlabel("Run Differential (Home − Away)")
    ax2.set_ylabel("Density")
    apply_dark(ax2, fig2)

    buf2 = io.BytesIO()
    fig2.savefig(buf2, format="png", bbox_inches="tight")
    plt.close(fig2)
    buf2.seek(0)
    run_image = base64.b64encode(buf2.getvalue()).decode("utf-8")

    context = {
        "game": game,
        "win_image": win_image,
        "run_image": run_image,
        "prediction": prediction,
    }

    return render(request, "games/prediction.html", context)
