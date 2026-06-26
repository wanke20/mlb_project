"""Build the games / hitters / bullpen CSV exports as strings.

Single source of truth for the CSV column layouts. The export views in
``games.views`` write these to an ``HttpResponse``; the pick assistant feeds
the same strings to the LLM as grounding context. Keeping one builder per CSV
means the download and the AI context can never drift apart.
"""

import csv
import io
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from games.models import Game, Hitter, Reliever
from games.services.dates import eastern_today
from games.services.mlb_api import get_game_pitchers
from games.templatetags.team_logos import logo_abbr


def resolve_date(day_param):
    """Map a ``today|yesterday|tomorrow`` query param to a concrete date."""
    today = eastern_today()
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
        "away_vs_lhb_avg", "home_vs_lhb_avg",
        "away_vs_lhb_ops", "home_vs_lhb_ops",
        "away_vs_lhb_bf", "home_vs_lhb_bf",
        "away_vs_rhb_avg", "home_vs_rhb_avg",
        "away_vs_rhb_ops", "home_vs_rhb_ops",
        "away_vs_rhb_bf", "home_vs_rhb_bf",
        "away_home_avg", "home_home_avg",
        "away_home_ops", "home_home_ops",
        "away_home_bf", "home_home_bf",
        "away_away_avg", "home_away_avg",
        "away_away_ops", "home_away_ops",
        "away_away_bf", "home_away_bf",
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
            ap.vs_l_avg or "" if ap else "", hp.vs_l_avg or "" if hp else "",
            ap.vs_l_ops or "" if ap else "", hp.vs_l_ops or "" if hp else "",
            ap.vs_l_bf if ap and ap.vs_l_bf is not None else "", hp.vs_l_bf if hp and hp.vs_l_bf is not None else "",
            ap.vs_r_avg or "" if ap else "", hp.vs_r_avg or "" if hp else "",
            ap.vs_r_ops or "" if ap else "", hp.vs_r_ops or "" if hp else "",
            ap.vs_r_bf if ap and ap.vs_r_bf is not None else "", hp.vs_r_bf if hp and hp.vs_r_bf is not None else "",
            ap.home_avg or "" if ap else "", hp.home_avg or "" if hp else "",
            ap.home_ops or "" if ap else "", hp.home_ops or "" if hp else "",
            ap.home_bf if ap and ap.home_bf is not None else "", hp.home_bf if hp and hp.home_bf is not None else "",
            ap.away_avg or "" if ap else "", hp.away_avg or "" if hp else "",
            ap.away_ops or "" if ap else "", hp.away_ops or "" if hp else "",
            ap.away_bf if ap and ap.away_bf is not None else "", hp.away_bf if hp and hp.away_bf is not None else "",
            rain_pct, has_roof,
            wind_mph, wind_dir, wind_relative,
            game.away_score if game.away_score is not None else "",
            game.home_score if game.home_score is not None else "",
            game.away_starter_runs if game.away_starter_runs is not None else "",
            game.home_starter_runs if game.home_starter_runs is not None else "",
        ])

    return out.getvalue()


def _bullpen_usage_for_tomorrow(team_ids):
    """Resolve each reliever's "pitched yesterday" status for the tomorrow slate.

    For a game tomorrow, "yesterday" is *today* — so the relevant question is
    who pitched in each team's game today. That game may not be finished yet, so
    per team:

      - game today is final        -> real appearances from today's boxscore
      - game today not final yet   -> "Incomplete" (we can't know who'll be used)
      - off today / postponed      -> "No" (nobody pitched the day before)

    Returns a ``resolve(reliever) -> (pitched_yesterday, yesterday_pitches)``
    callable. Today's boxscores are fetched lazily, once per game.
    """
    today = eastern_today()
    team_today_game = {}
    for g in Game.objects.filter(date=today):
        team_today_game[g.home_team_id] = g
        team_today_game[g.away_team_id] = g

    status_by_team = {}        # team_id -> "completed" | "incomplete" | "rested"
    pitches_by_mlb_id = {}     # mlb_id -> pitches thrown today
    fetched = {}               # game_id -> appearances (shared game fetched once)
    for team_id in team_ids:
        game = team_today_game.get(team_id)
        if game is None or game.postponed:
            status_by_team[team_id] = "rested"
        elif game.home_score is not None:
            status_by_team[team_id] = "completed"
            if game.game_id not in fetched:
                try:
                    fetched[game.game_id] = get_game_pitchers(game.game_id)
                except Exception:
                    fetched[game.game_id] = {}
            pitches_by_mlb_id.update(fetched[game.game_id])
        else:
            status_by_team[team_id] = "incomplete"

    def resolve(reliever):
        status = status_by_team.get(reliever.team_id, "rested")
        if status == "incomplete":
            return "Incomplete", "Incomplete"
        if status == "completed":
            pitches = pitches_by_mlb_id.get(reliever.mlb_id)
            if pitches is not None:
                return "Yes", pitches
        return "No", ""

    return resolve


def build_bullpen_csv(day_param="today"):
    """Relievers for the teams playing on ``day_param`` (today or tomorrow),
    grouped by team and ordered by appearances.

    The ``pitched_yesterday`` columns are relative to the slate's own date: for
    a given game, "yesterday" is the day before it. For the *today* slate that
    is the stored ``pitched_yesterday`` flag (the previous day's appearances,
    set by fetch_games). For the *tomorrow* slate the relevant day is today —
    whose games may still be in progress — so the status is derived live; see
    ``_bullpen_usage_for_tomorrow``.
    """
    target_date = resolve_date(day_param)

    team_ids = set()
    for home_id, away_id in Game.objects.filter(date=target_date).values_list(
        "home_team_id", "away_team_id"
    ):
        team_ids.add(home_id)
        team_ids.add(away_id)

    tomorrow_usage = (
        _bullpen_usage_for_tomorrow(team_ids) if day_param == "tomorrow" else None
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "team", "reliever", "appearances", "era", "saves", "holds",
        "pitched_yesterday", "yesterday_pitches",
    ])
    relievers = (
        Reliever.objects.select_related("team")
        .filter(team_id__in=team_ids)
        .order_by("team__name", "-season_appearances")
    )
    for r in relievers:
        if tomorrow_usage is not None:
            pitched_yesterday, yesterday_pitches = tomorrow_usage(r)
        else:
            pitched_yesterday = "Yes" if r.pitched_yesterday else "No"
            yesterday_pitches = (
                r.yesterday_pitches if r.yesterday_pitches is not None else ""
            )
        writer.writerow([
            r.team.name,
            r.name,
            r.season_appearances,
            r.era if r.era is not None else "",
            r.saves,
            r.holds,
            pitched_yesterday,
            yesterday_pitches,
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
