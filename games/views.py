import csv
import json
import math
from statistics import NormalDist

from datetime import date, timedelta

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.db.models import F, Prefetch
from django.utils import timezone
from .models import Game, Team, Reliever, Hitter
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
    today = date.today()
    day_param = request.GET.get("date", "today")
    if day_param == "yesterday":
        target_date = today - timedelta(days=1)
    elif day_param == "tomorrow":
        target_date = today + timedelta(days=1)
    else:
        day_param = "today"
        target_date = today

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
    hitter_qs = Hitter.objects.order_by('rank')
    game = get_object_or_404(
        Game.objects.select_related(
            "home_team", "away_team", "home_pitcher", "away_pitcher"
        ).prefetch_related(
            Prefetch('home_team__relievers', queryset=reliever_qs),
            Prefetch('away_team__relievers', queryset=reliever_qs),
            Prefetch('home_team__hitters', queryset=hitter_qs),
            Prefetch('away_team__hitters', queryset=hitter_qs),
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
        "away_relievers": list(game.away_team.relievers.all()[:5]),
        "home_relievers": list(game.home_team.relievers.all()[:5]),
        "away_hitters": list(game.away_team.hitters.all()),
        "home_hitters": list(game.home_team.hitters.all()),
        "win_chart": chart_json(x_win, y_win),
        "run_chart": chart_json(x_run, y_run),
        "total_chart": chart_json(x_total, y_total),
    }

    return render(request, "games/prediction.html", context)


def export_csv(request):
    today = date.today()
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
    response["Content-Disposition"] = f'attachment; filename="mlb_export_{target_date}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "date", "start_time_et",
        "away_team", "home_team",
        "away_record", "home_record",
        "away_last10", "home_last10",
        "away_streak", "home_streak",
        "away_win_pct", "home_win_pct",
        "away_season_avg", "home_season_avg",
        "away_season_ops", "home_season_ops",
        "away_pitcher", "home_pitcher",
        "away_pitcher_throws", "home_pitcher_throws",
        "away_era", "home_era",
        "away_whip", "home_whip",
        "away_strikeouts", "home_strikeouts",
        "away_innings_pitched", "home_innings_pitched",
        "away_fip", "home_fip",
        "away_xera", "home_xera",
        "away_woba", "home_woba",
        "away_xwoba", "home_xwoba",
        "away_k_bb_pct", "home_k_bb_pct",
        "away_barrel_pct", "home_barrel_pct",
        "rain_pct", "has_roof",
        "away_score", "home_score",
        "away_starter_er", "home_starter_er",
    ])

    eastern = timezone.get_fixed_timezone(-240)  # EDT (UTC-4); close enough for display

    for game in games:
        start_et = game.start_time_utc.astimezone(eastern).strftime("%Y-%m-%d %I:%M %p") if game.start_time_utc else ""

        away, home = game.away_team, game.home_team
        ap, hp = game.away_pitcher, game.home_pitcher

        try:
            w = game.weather
            rain_pct = w.rain_pct
            has_roof = "Yes" if w.has_roof else "No"
        except Exception:
            rain_pct = ""
            has_roof = ""

        writer.writerow([
            game.date,
            start_et,
            away.name, home.name,
            f"{away.wins}-{away.losses}" if away.wins is not None else "",
            f"{home.wins}-{home.losses}" if home.wins is not None else "",
            f"{away.last10_wins}-{away.last10_losses}",
            f"{home.last10_wins}-{home.last10_losses}",
            f"{away.streak_type}{away.streak_length}" if away.streak_type else "",
            f"{home.streak_type}{home.streak_length}" if home.streak_type else "",
            away.win_pct, home.win_pct,
            away.season_avg, home.season_avg,
            away.season_ops, home.season_ops,
            ap.name if ap else "", hp.name if hp else "",
            ap.throws if ap else "", hp.throws if hp else "",
            ap.era if ap else "", hp.era if hp else "",
            ap.whip if ap else "", hp.whip if hp else "",
            ap.strikeouts if ap else "", hp.strikeouts if hp else "",
            ap.innings_pitched if ap else "", hp.innings_pitched if hp else "",
            ap.fip if ap else "", hp.fip if hp else "",
            ap.xera if ap else "", hp.xera if hp else "",
            ap.woba if ap else "", hp.woba if hp else "",
            ap.xwoba if ap else "", hp.xwoba if hp else "",
            ap.k_bb_pct if ap else "", hp.k_bb_pct if hp else "",
            ap.barrel_pct if ap else "", hp.barrel_pct if hp else "",
            rain_pct, has_roof,
            game.away_score if game.away_score is not None else "",
            game.home_score if game.home_score is not None else "",
            game.away_starter_runs if game.away_starter_runs is not None else "",
            game.home_starter_runs if game.home_starter_runs is not None else "",
        ])

    return response


def export_results_csv(request):
    today = date.today()
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
        ])

    return response


def export_bullpen_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_bullpen_{date.today()}.csv"'

    writer = csv.writer(response)
    writer.writerow(["team", "reliever", "appearances", "era", "saves", "holds", "pitched_yesterday", "yesterday_pitches"])

    for r in Reliever.objects.select_related("team").order_by("team__name", "-season_appearances"):
        writer.writerow([
            r.team.name,
            r.name,
            r.season_appearances,
            r.era if r.era is not None else "",
            r.saves,
            r.holds,
            "Yes" if r.pitched_yesterday else "No",
            r.yesterday_pitches if r.yesterday_pitches is not None else "",
        ])

    return response


def export_hitters_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="mlb_hitters_{date.today()}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "team", "rank", "hitter", "bats",
        "season_pa", "season_avg", "season_ops",
        "vs_lhp_pa", "vs_lhp_avg", "vs_lhp_ops",
        "vs_rhp_pa", "vs_rhp_avg", "vs_rhp_ops",
    ])

    for h in Hitter.objects.select_related("team").order_by("team__name", "rank"):
        writer.writerow([
            h.team.name,
            h.rank if h.rank is not None else "",
            h.name,
            h.bats or "",
            h.season_pa if h.season_pa is not None else "",
            h.season_avg or "",
            h.season_ops or "",
            h.vs_l_pa if h.vs_l_pa is not None else "",
            h.vs_l_avg or "",
            h.vs_l_ops or "",
            h.vs_r_pa if h.vs_r_pa is not None else "",
            h.vs_r_avg or "",
            h.vs_r_ops or "",
        ])

    return response
