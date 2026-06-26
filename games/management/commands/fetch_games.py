from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime
from games.models import Team, Pitcher, Game, Reliever
from games.services.mlb_api import (
    get_schedule, get_pitcher_stats, get_standings, get_teams,
    get_team_season_hitting_stats, get_team_last7_hitting_stats,
    get_team_reliever_stats, get_game_pitchers, get_game_result,
)
from games.services.savant_stats import get_savant_leaderboard
from datetime import datetime, timedelta

from games.services.dates import eastern_today

import logging
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch MLB games, pitchers, and 2026 team records, and store in DB"

    def handle(self, *args, **kwargs):
        # -----------------------
        # Step 1: Update team records
        # -----------------------
        try:
            standings = get_standings(season=2026)
        except Exception as e:
            logger.error(f"Failed to fetch standings: {e}")
            return
        
        total_teams = 0

        with transaction.atomic():
            for record_group in standings.get("records", []):
                for team_record in record_group.get("teamRecords", []):
                    team_id = team_record["team"]["id"]
                    
                    wins = team_record["wins"]
                    losses = team_record["losses"]
                    pct = float(team_record["winningPercentage"])
                    
                    # -----------------------
                    # Last 10
                    # -----------------------
                    last10_wins = 0
                    last10_losses = 0

                    for split in team_record.get("records", {}).get("splitRecords", []):
                        if split.get("type") == "lastTen":
                            last10_wins = split.get("wins", 0)
                            last10_losses = split.get("losses", 0)
                            break

                    streak = team_record.get("streak", {})
                    streak_type = None
                    streak_length = None
                    if streak.get("streakType") == "wins":
                        streak_type = "W"
                        streak_length = streak.get("streakNumber")
                    elif streak.get("streakType") == "losses":
                        streak_type = "L"
                        streak_length = streak.get("streakNumber")

                    Team.objects.update_or_create(
                        mlb_id=team_id,
                        defaults={
                            "name": team_record["team"]["name"],
                            "abbreviation": team_record["team"].get("abbreviation", "").lower(),
                            "wins": wins,
                            "losses": losses,
                            "win_pct": pct,
                            "last10_wins": last10_wins,
                            "last10_losses": last10_losses,
                            "streak_type": streak_type,
                            "streak_length": streak_length,
                        }
                    )
                    total_teams += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {total_teams} teams for 2026 records.")
        )

        # -----------------------
        # Step 1.5: Populate team abbreviations
        # The standings/schedule team blocks omit abbreviation, so pull the
        # canonical abbreviations from the teams endpoint.
        # -----------------------
        try:
            abbr_updated = 0
            for t in get_teams(season=2026):
                if t.get("abbreviation"):
                    abbr_updated += Team.objects.filter(mlb_id=t["mlb_id"]).update(
                        abbreviation=t["abbreviation"].lower()
                    )
            self.stdout.write(
                self.style.SUCCESS(f"Updated abbreviations for {abbr_updated} teams.")
            )
        except Exception as e:
            logger.error(f"Failed to fetch team abbreviations: {e}")

        # -----------------------
        # Step 2: Update season hitting stats
        # -----------------------
        try:
            season_stats = get_team_season_hitting_stats(season=2026)
            for team_id, stats in season_stats.items():
                Team.objects.filter(mlb_id=team_id).update(
                    season_avg=stats["avg"],
                    season_ops=stats["ops"],
                    season_runs=stats["runs"],
                    season_strikeouts=stats["strikeouts"],
                )
            self.stdout.write(
                self.style.SUCCESS(f"Updated season hitting stats for {len(season_stats)} teams.")
            )
        except Exception as e:
            logger.error(f"Failed to fetch season hitting stats: {e}")

        # -----------------------
        # Step 3: Update last 7 days runs
        # -----------------------
        try:
            last7_stats = get_team_last7_hitting_stats(season=2026)
            for team_id, stats in last7_stats.items():
                Team.objects.filter(mlb_id=team_id).update(
                    last7_avg=stats["avg"],
                    last7_runs=stats["runs"],
                )
            self.stdout.write(
                self.style.SUCCESS(f"Updated last-7-day runs for {len(last7_stats)} teams.")
            )
        except Exception as e:
            logger.error(f"Failed to fetch last-7-day hitting stats: {e}")

        # -----------------------
        # Step 3.5: Fetch Baseball Savant Statcast leaderboard (one bulk pull)
        # -----------------------
        try:
            advanced_pitching = get_savant_leaderboard(year=2026)
            self.stdout.write(
                self.style.SUCCESS(f"Fetched Statcast stats for {len(advanced_pitching)} pitchers.")
            )
        except Exception as e:
            logger.error(f"Failed to fetch Savant leaderboard: {e}")
            advanced_pitching = {}

        # -----------------------
        # Step 4: Update games and probable pitchers (today + tomorrow)
        # -----------------------
        today = eastern_today()
        tomorrow = today + timedelta(days=1)
        fetch_dates = [today, tomorrow]
        total_games = 0

        # Track every game_id we see in the fresh schedule so we can prune
        # only the games that have actually dropped off (cancelled/rescheduled)
        # AFTER the upsert. We deliberately do NOT bulk-delete games up front:
        # Pick and WeatherData cascade-delete with their Game, so a blanket
        # delete would wipe user picks and weather every run. update_or_create
        # below keeps existing games (and their related rows) intact.
        fetched_game_ids = set()

        # Game ids the schedule reports as completed ("Final"). Used below so we
        # only pull final scores for games that have actually finished — a live
        # or not-yet-started game would otherwise get a partial/zero score
        # written and be rendered as "Final" in the UI.
        final_game_ids = set()

        for fetch_date in fetch_dates:
            try:
                data = get_schedule(game_date=fetch_date.strftime("%Y-%m-%d"))
            except Exception as e:
                logger.error(f"Failed to fetch schedule for {fetch_date}: {e}")
                continue

            for d in data.get("dates", []):
                game_date = datetime.strptime(d["date"], "%Y-%m-%d").date()

                for game in d.get("games", []):
                    game_id = game["gamePk"]
                    fetched_game_ids.add(game_id)
                    status = game.get("status", {})
                    is_postponed = status.get("detailedState") == "Postponed"
                    if status.get("abstractGameState") == "Final" and not is_postponed:
                        final_game_ids.add(game_id)
                    game_start_utc = parse_datetime(game.get("gameDate")) if game.get("gameDate") else None

                    # -----------------------
                    # Teams
                    # -----------------------
                    home_data = game["teams"]["home"]["team"]
                    away_data = game["teams"]["away"]["team"]

                    home_defaults = {"name": home_data["name"]}
                    home_abbr = (home_data.get("abbreviation") or "").strip()
                    if home_abbr:
                        home_defaults["abbreviation"] = home_abbr.lower()

                    home_team, _ = Team.objects.update_or_create(
                        mlb_id=home_data["id"],
                        defaults=home_defaults
                    )

                    away_defaults = {"name": away_data["name"]}
                    away_abbr = (away_data.get("abbreviation") or "").strip()
                    if away_abbr:
                        away_defaults["abbreviation"] = away_abbr.lower()

                    away_team, _ = Team.objects.update_or_create(
                        mlb_id=away_data["id"],
                        defaults=away_defaults
                    )

                    # -----------------------
                    # Pitcher Helper
                    # -----------------------
                    def process_pitcher(team_block):
                        pitcher_data = team_block.get("probablePitcher")
                        if not pitcher_data:
                            return None

                        pitcher_id = pitcher_data["id"]

                        try:
                            pitcher_stats = get_pitcher_stats(pitcher_id)
                        except Exception as e:
                            logger.error(f"Failed to fetch pitcher stats: {e}")
                            return

                        defaults = {
                            "name": pitcher_data["fullName"],
                            "throws": pitcher_stats.get("throws"),
                            "era": pitcher_stats["era"],
                            "whip": pitcher_stats["whip"],
                            "strikeouts": pitcher_stats["strikeouts"],
                            "walks": pitcher_stats["walks"],
                            "innings_pitched": pitcher_stats["innings_pitched"],
                            "fip": pitcher_stats.get("fip"),
                            "k_bb_pct": pitcher_stats.get("k_bb_pct"),
                            "vs_l_avg": pitcher_stats.get("vs_l_avg"),
                            "vs_l_ops": pitcher_stats.get("vs_l_ops"),
                            "vs_l_bf": pitcher_stats.get("vs_l_bf"),
                            "vs_r_avg": pitcher_stats.get("vs_r_avg"),
                            "vs_r_ops": pitcher_stats.get("vs_r_ops"),
                            "vs_r_bf": pitcher_stats.get("vs_r_bf"),
                            "home_avg": pitcher_stats.get("home_avg"),
                            "home_ops": pitcher_stats.get("home_ops"),
                            "home_bf": pitcher_stats.get("home_bf"),
                            "away_avg": pitcher_stats.get("away_avg"),
                            "away_ops": pitcher_stats.get("away_ops"),
                            "away_bf": pitcher_stats.get("away_bf"),
                        }

                        advanced = advanced_pitching.get(pitcher_id)
                        if advanced:
                            defaults.update(advanced)

                        pitcher, _ = Pitcher.objects.update_or_create(
                            mlb_id=pitcher_id,
                            defaults=defaults,
                        )

                        return pitcher

                    home_pitcher = process_pitcher(game["teams"]["home"])
                    away_pitcher = process_pitcher(game["teams"]["away"])

                    # -----------------------
                    # Game
                    # -----------------------
                    Game.objects.update_or_create(
                        game_id=game_id,
                        defaults={
                            "date": game_date,
                            "start_time_utc": game_start_utc,
                            "home_team": home_team,
                            "away_team": away_team,
                            "home_pitcher": home_pitcher,
                            "away_pitcher": away_pitcher,
                            "postponed": is_postponed,
                        }
                    )

                    total_games += 1

        # Prune only games that have dropped off the schedule for these dates
        # (e.g. cancelled or rescheduled). Games that still exist are left
        # untouched, so their picks and weather survive the refresh.
        with transaction.atomic():
            stale_games = Game.objects.filter(date__in=fetch_dates).exclude(
                game_id__in=fetched_game_ids
            )
            deleted_games, _ = stale_games.delete()
        if deleted_games:
            self.stdout.write(
                self.style.WARNING(f"Removed {deleted_games} stale games no longer on the schedule.")
            )

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {total_games} games.")
        )

        # -----------------------
        # Step 5: Fetch top relievers and mark yesterday's appearances
        # -----------------------
        upcoming_team_ids = set()
        for game in Game.objects.filter(date__in=[today, tomorrow]).select_related("home_team", "away_team"):
            upcoming_team_ids.add(game.home_team.mlb_id)
            upcoming_team_ids.add(game.away_team.mlb_id)

        Reliever.objects.filter(team__mlb_id__in=upcoming_team_ids).update(
            pitched_yesterday=False, yesterday_pitches=None
        )

        for team in Team.objects.filter(mlb_id__in=upcoming_team_ids):
            try:
                team_relievers = get_team_reliever_stats(team.mlb_id)
            except Exception as e:
                logger.error(f"Failed to fetch relievers for team {team.mlb_id}: {e}")
                continue

            top_relievers = team_relievers[:10]
            for r in top_relievers:
                Reliever.objects.update_or_create(
                    mlb_id=r["mlb_id"],
                    defaults={
                        "name": r["name"],
                        "team": team,
                        "season_appearances": r["appearances"],
                        "saves": r["saves"],
                        "holds": r["holds"],
                        "era": r["era"],
                    }
                )

            # Prune relievers no longer in this team's top set (traded away,
            # demoted, or converted to starting). Without this, update_or_create
            # only ever adds rows, so stale pitchers linger on the team and can
            # surface in today's bullpen. Only runs when the fetch succeeded
            # (the except above `continue`s), so a failed API call can't wipe a
            # team's bullpen.
            fetched_ids = {r["mlb_id"] for r in top_relievers}
            Reliever.objects.filter(team=team).exclude(mlb_id__in=fetched_ids).delete()

        self.stdout.write(self.style.SUCCESS("Updated reliever rosters."))

        yesterday = today - timedelta(days=1)
        for game in Game.objects.filter(date=yesterday):
            try:
                pitchers = get_game_pitchers(game.game_id)
            except Exception as e:
                logger.error(f"Failed to fetch boxscore for game {game.game_id}: {e}")
                continue

            for pitcher_id, pitches in pitchers.items():
                Reliever.objects.filter(mlb_id=pitcher_id).update(
                    pitched_yesterday=True,
                    yesterday_pitches=pitches,
                )

        self.stdout.write(self.style.SUCCESS("Marked yesterday's reliever appearances."))

        # Hitters are populated entirely by the fetch_lineups command (the
        # actual projected batting order), not here — there is no top-6 baseline.

        # -----------------------
        # Step 6: Fetch final scores for completed games.
        # Yesterday's games are always finished by the time this runs. Today's
        # games are included only when the schedule reported them as "Final",
        # so a game still in progress isn't written with a partial score and
        # shown as "Final" in the UI. This lets today's results appear the same
        # day they complete rather than waiting for the next day's run.
        #
        # Games that already have a stored score are skipped: a final score is
        # immutable, so re-fetching it just wastes an HTTP call per game.
        # -----------------------
        result_games = list(
            Game.objects.filter(date=yesterday, home_score__isnull=True)
        ) + list(
            Game.objects.filter(
                date=today, game_id__in=final_game_ids, home_score__isnull=True
            )
        )
        results_updated = 0
        for game in result_games:
            try:
                result = get_game_result(game.game_id)
                Game.objects.filter(pk=game.pk).update(**result)
                results_updated += 1
            except Exception as e:
                logger.error(f"Failed to fetch result for game {game.game_id}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Fetched final scores for {results_updated} games."))
