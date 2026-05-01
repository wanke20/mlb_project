from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime
from games.models import Team, Pitcher, Game, Reliever
from games.services.mlb_api import (
    get_schedule, get_pitcher_stats, get_standings,
    get_team_season_hitting_stats, get_team_last7_hitting_stats,
    get_team_reliever_stats, get_game_pitchers, get_game_result,
)
from datetime import datetime, date, timedelta

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
        # Step 4: Update games and probable pitchers (today + tomorrow)
        # -----------------------
        today = date.today()
        tomorrow = today + timedelta(days=1)
        fetch_dates = [today, tomorrow]
        total_games = 0

        with transaction.atomic():
            deleted_games, _ = Game.objects.filter(date__in=fetch_dates).delete()
            self.stdout.write(
                self.style.WARNING(f"Removed {deleted_games} existing games before refresh.")
            )

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

                        pitcher, _ = Pitcher.objects.update_or_create(
                            mlb_id=pitcher_id,
                            defaults={
                                "name": pitcher_data["fullName"],
                                "era": pitcher_stats["era"],
                                "whip": pitcher_stats["whip"],
                                "strikeouts": pitcher_stats["strikeouts"],
                                "walks": pitcher_stats["walks"],
                                "innings_pitched": pitcher_stats["innings_pitched"],
                            }
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
                            "away_pitcher": away_pitcher
                        }
                    )

                    total_games += 1

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

            for r in team_relievers[:10]:
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

        # -----------------------
        # Step 6: Fetch final scores for yesterday's completed games
        # -----------------------
        results_updated = 0
        for game in Game.objects.filter(date=yesterday, home_score__isnull=True):
            try:
                result = get_game_result(game.game_id)
                Game.objects.filter(pk=game.pk).update(**result)
                results_updated += 1
            except Exception as e:
                logger.error(f"Failed to fetch result for game {game.game_id}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Fetched final scores for {results_updated} games."))
