import csv
import json
import math
from statistics import NormalDist

from datetime import timedelta

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.db.models import F, Prefetch
from .models import Game, Team, Reliever, Hitter
from games.services.prediction import predict_game
from games.services.csv_exports import (
    build_games_csv,
    build_bullpen_csv,
    build_hitters_csv,
    resolve_date,
)
from games.services.dates import eastern_today


def _linspace(start, stop, n):
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


def _avg_rate(values):
    """Mean of rate-stat strings (AVG/OPS), formatted like '.275' / '1.025'.

    The values are stored as strings and may be missing or blank; only the
    parseable ones are averaged. Returns None when none can be parsed.
    """
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    formatted = f"{sum(nums) / len(nums):.3f}"
    # MLB convention drops the leading zero on sub-1.000 rate stats (.275).
    return formatted[1:] if formatted.startswith("0.") else formatted


def _lineup_averages(hitters):
    """Unweighted mean of a lineup's season and platoon rate stats."""
    return {
        "season_avg": _avg_rate(h.season_avg for h in hitters),
        "season_ops": _avg_rate(h.season_ops for h in hitters),
        "vs_l_avg": _avg_rate(h.vs_l_avg for h in hitters),
        "vs_l_ops": _avg_rate(h.vs_l_ops for h in hitters),
        "vs_r_avg": _avg_rate(h.vs_r_avg for h in hitters),
        "vs_r_ops": _avg_rate(h.vs_r_ops for h in hitters),
    }


def home_page(request):
    return render(request, "games/home.html")


def trends(request):
    teams = Team.objects.filter(wins__isnull=False).order_by("-wins", "losses")
    return render(request, "games/trends.html", {"teams": teams})


def _resolve_target_date(request):
    """Map the ?date=today|yesterday|tomorrow param to (day_param, date)."""
    today = eastern_today()
    day_param = request.GET.get("date", "today")
    if day_param == "yesterday":
        return "yesterday", today - timedelta(days=1)
    if day_param == "tomorrow":
        return "tomorrow", today + timedelta(days=1)
    return "today", today


def game_list(request):
    day_param, target_date = _resolve_target_date(request)

    games = Game.objects.select_related(
        "home_team", "away_team", "home_pitcher", "away_pitcher"
    ).filter(date=target_date).order_by(F("start_time_utc").asc(nulls_last=True), "game_id")

    return render(request, "games/game_list.html", {
        "games": games,
        "selected_day": day_param,
        "target_date": target_date,
    })


def game_prediction(request, game_id):
    reliever_qs = Reliever.objects.order_by('-season_appearances')
    game = get_object_or_404(
        Game.objects.select_related(
            "home_team", "away_team", "home_pitcher", "away_pitcher"
        ).prefetch_related(
            Prefetch('home_team__relievers', queryset=reliever_qs),
            Prefetch('away_team__relievers', queryset=reliever_qs),
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

    user_pick = None
    if request.user.is_authenticated:
        user_pick = game.picks.filter(user=request.user).first()

    away_hitters = list(game.away_team.hitters.filter(date=game.date).order_by("rank"))
    home_hitters = list(game.home_team.hitters.filter(date=game.date).order_by("rank"))

    context = {
        "game": game,
        "prediction": prediction,
        "user_pick": user_pick,
        "away_relievers": list(game.away_team.relievers.all()[:5]),
        "home_relievers": list(game.home_team.relievers.all()[:5]),
        "away_hitters": away_hitters,
        "home_hitters": home_hitters,
        "away_lineup_avg": _lineup_averages(away_hitters),
        "home_lineup_avg": _lineup_averages(home_hitters),
        "win_chart": chart_json(x_win, y_win),
        "run_chart": chart_json(x_run, y_run),
        "total_chart": chart_json(x_total, y_total),
    }

    return render(request, "games/prediction.html", context)


def export_csv(request):
    target_date = resolve_date(request.GET.get("date", "today"))
    response = HttpResponse(build_games_csv(target_date), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_export_{target_date}.csv"'
    return response


def export_results_csv(request):
    today = eastern_today()
    day_param = request.GET.get("date", "today")
    if day_param == "yesterday":
        target_date = today - timedelta(days=1)
    elif day_param == "tomorrow":
        target_date = today + timedelta(days=1)
    else:
        target_date = today

    games = Game.objects.select_related(
        "home_team", "away_team", "home_pitcher", "away_pitcher"
    ).filter(date=target_date).order_by(F("start_time_utc").asc(nulls_last=True))

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_results_{target_date}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "date", "away_team", "home_team",
        "away_score", "home_score", "winner",
        "away_starter", "away_starter_throws", "away_starter_er", "away_starter_ip",
        "home_starter", "home_starter_throws", "home_starter_er", "home_starter_ip",
        "away_record", "home_record",
        "away_era", "home_era",
        "away_fip", "home_fip",
        "away_xera", "home_xera",
        "away_xwoba", "home_xwoba",
        "away_k_bb_pct", "home_k_bb_pct",
        "away_barrel_pct", "home_barrel_pct",
        "away_vs_lhb_avg", "home_vs_lhb_avg",
        "away_vs_lhb_ops", "home_vs_lhb_ops",
        "away_vs_rhb_avg", "home_vs_rhb_avg",
        "away_vs_rhb_ops", "home_vs_rhb_ops",
        "away_home_avg", "home_home_avg",
        "away_home_ops", "home_home_ops",
        "away_away_avg", "home_away_avg",
        "away_away_ops", "home_away_ops",
    ])

    for game in games:
        away, home = game.away_team, game.home_team
        ap, hp = game.away_pitcher, game.home_pitcher
        writer.writerow([
            game.date,
            away.name, home.name,
            game.away_score if game.away_score is not None else "",
            game.home_score if game.home_score is not None else "",
            away.name if game.away_score is not None and game.home_score is not None and game.away_score > game.home_score else home.name if game.away_score is not None and game.home_score is not None else "",
            ap.name if ap else "",
            ap.throws if ap else "",
            game.away_starter_runs if game.away_starter_runs is not None else "",
            game.away_starter_innings or "",
            hp.name if hp else "",
            hp.throws if hp else "",
            game.home_starter_runs if game.home_starter_runs is not None else "",
            game.home_starter_innings or "",
            f"{away.wins}-{away.losses}" if away.wins is not None else "",
            f"{home.wins}-{home.losses}" if home.wins is not None else "",
            ap.era if ap else "",
            hp.era if hp else "",
            ap.fip if ap else "", hp.fip if hp else "",
            ap.xera if ap else "", hp.xera if hp else "",
            ap.xwoba if ap else "", hp.xwoba if hp else "",
            ap.k_bb_pct if ap else "", hp.k_bb_pct if hp else "",
            ap.barrel_pct if ap else "", hp.barrel_pct if hp else "",
            ap.vs_l_avg or "" if ap else "", hp.vs_l_avg or "" if hp else "",
            ap.vs_l_ops or "" if ap else "", hp.vs_l_ops or "" if hp else "",
            ap.vs_r_avg or "" if ap else "", hp.vs_r_avg or "" if hp else "",
            ap.vs_r_ops or "" if ap else "", hp.vs_r_ops or "" if hp else "",
            ap.home_avg or "" if ap else "", hp.home_avg or "" if hp else "",
            ap.home_ops or "" if ap else "", hp.home_ops or "" if hp else "",
            ap.away_avg or "" if ap else "", hp.away_avg or "" if hp else "",
            ap.away_ops or "" if ap else "", hp.away_ops or "" if hp else "",
        ])

    return response


def export_bullpen_csv(request):
    day_param = request.GET.get("date", "today")
    if day_param not in ("today", "tomorrow"):
        day_param = "today"
    target_date = resolve_date(day_param)
    response = HttpResponse(build_bullpen_csv(day_param), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_bullpen_{target_date}.csv"'
    return response


def export_hitters_csv(request):
    _, target_date = _resolve_target_date(request)
    response = HttpResponse(build_hitters_csv(target_date), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_hitters_{target_date}.csv"'
    return response
