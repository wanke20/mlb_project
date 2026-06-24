"""Build the games / hitters / bullpen CSV exports as strings.

Single source of truth for the CSV column layouts. The export views in
``games.views`` write these to an ``HttpResponse``; the pick assistant feeds
the same strings to the LLM as grounding context. Keeping one builder per CSV
means the download and the AI context can never drift apart.
"""

import csv
import io
from datetime import date, timedelta

from django.db.models import F
from django.utils import timezone

from games.models import Game, Hitter, Reliever
from games.templatetags.team_logos import logo_abbr


def resolve_date(day_param):
    """Map a ``today|yesterday|tomorrow`` query param to a concrete date."""
    today = date.today()
    if day_param == "yesterday":
        return today - timedelta(days=1)
    if day_param == "tomorrow":
        return today + timedelta(days=1)
    return today


def _games_for(target_date):
    return (
        Game.objects.select_related(
            "home_team", "away_team", "home_pitcher", "away_pitcher"
        )
        .filter(date=target_date)
        .order_by(F("start_time_utc").asc(nulls_last=True), "game_id")
    )


def build_games_csv(target_date):
    """Full per-game export: records, pitcher basic + advanced stats, weather, results."""
    out = io.StringIO()
    writer = csv.writer(out)
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
        "wind_mph", "wind_dir", "wind_relative",
        "away_score", "home_score",
        "away_starter_er", "home_starter_er",
    ])

    eastern = timezone.get_fixed_timezone(-240)  # EDT (UTC-4); close enough for display

    for game in _games_for(target_date):
        start_et = (
            game.start_time_utc.astimezone(eastern).strftime("%Y-%m-%d %I:%M %p")
            if game.start_time_utc else ""
        )
        away, home = game.away_team, game.home_team
        ap, hp = game.away_pitcher, game.home_pitcher 

        try:
            w = game.weather
            rain_pct = w.rain_pct
            has_roof = "Yes" if w.has_roof else "No"
            if w.has_roof:
                wind_mph = wind_dir = wind_relative = "Dome / Roof"
            else:
                wind_mph = w.wind_mph if w.wind_mph is not None else ""
                wind_dir = w.wind_dir or ""
                wind_relative = w.wind_relative or ""
        except Exception:
            rain_pct = ""
            has_roof = ""
            wind_mph = ""
            wind_dir = ""
            wind_relative = ""

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
            f"{ap.name} ({logo_abbr(away).upper() or away.name})" if ap else "",
            f"{hp.name} ({logo_abbr(home).upper() or home.name})" if hp else "",
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
            wind_mph, wind_dir, wind_relative,
            game.away_score if game.away_score is not None else "",
            game.home_score if game.home_score is not None else "",
            game.away_starter_runs if game.away_starter_runs is not None else "",
            game.home_starter_runs if game.home_starter_runs is not None else "",
        ])

    return out.getvalue()


def build_bullpen_csv():
    """All relievers, grouped by team, ordered by appearances."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "team", "reliever", "appearances", "era", "saves", "holds",
        "pitched_yesterday", "yesterday_pitches",
    ])
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
    return out.getvalue()


def build_hitters_csv(target_date=None):
    """Hitters with season + platoon splits, grouped by team and lineup rank.

    Pass target_date to export only that date's lineups; otherwise all dates.
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "team", "date", "rank", "hitter", "position", "bats",
        "season_pa", "season_avg", "season_ops",
        "vs_lhp_pa", "vs_lhp_avg", "vs_lhp_ops",
        "vs_rhp_pa", "vs_rhp_avg", "vs_rhp_ops",
    ])
    hitters = Hitter.objects.select_related("team")
    if target_date is not None:
        hitters = hitters.filter(date=target_date)
    for h in hitters.order_by("team__name", "date", "rank"):
        writer.writerow([
            h.team.name,
            h.date.isoformat() if h.date else "",
            h.rank if h.rank is not None else "",
            h.name,
            h.position or "",
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
    return out.getvalue()
