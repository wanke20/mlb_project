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

    BG      = "#27273a"
    SURFACE = "#1e1e2e"
    TEXT    = "#cdd6f4"
    MUTED   = "#7f849c"
    ACCENT  = "#89b4fa"
    GRID    = "#45475a"

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

    # ------------------------
    # Run Total Distribution
    # ------------------------
    mu_total = prediction["expected_total"]
    sigma_total = 3.0

    x3 = np.linspace(mu_total - 4*sigma_total, mu_total + 4*sigma_total, 400)
    y3 = norm.pdf(x3, mu_total, sigma_total)

    fig3, ax3 = plt.subplots()
    ax3.plot(x3, y3, color="#a6e3a1", linewidth=1.8)
    ax3.set_title("Run Total Distribution")
    ax3.set_xlabel("Total Runs (Both Teams)")
    ax3.set_ylabel("Density")
    apply_dark(ax3, fig3)

    buf3 = io.BytesIO()
    fig3.savefig(buf3, format="png", bbox_inches="tight")
    plt.close(fig3)
    buf3.seek(0)
    total_image = base64.b64encode(buf3.getvalue()).decode("utf-8")

    context = {
        "game": game,
        "win_image": win_image,
        "run_image": run_image,
        "total_image": total_image,
        "prediction": prediction,
    }

    return render(request, "games/prediction.html", context)
