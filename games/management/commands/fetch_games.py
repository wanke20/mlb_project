from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime
from games.models import Team, Pitcher, Game
from games.services.mlb_api import get_schedule, get_pitcher_stats, get_standings
from datetime import datetime

import logging
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch MLB games, pitchers, and 2025 team records, and store in DB"

    def handle(self, *args, **kwargs):
        # -----------------------
        # Step 1: Update team records
        # -----------------------
        try:
            standings = get_standings(season=2025)
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

                    Team.objects.update_or_create(
                        mlb_id=team_id,
                        defaults={
                            "name": team_record["team"]["name"],
                            "wins": wins,
                            "losses": losses,
                            "win_pct": pct,
                            "last10_wins": last10_wins,
                            "last10_losses": last10_losses
                        }
                    )
                    total_teams += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {total_teams} teams for 2025 records.")
        )

        # -----------------------
        # Step 2: Update games and probable pitchers
        # -----------------------
        try:
            data = get_schedule()
        except Exception as e:
            logger.error(f"Failed to fetch schedule: {e}")
            return
        
        total_games = 0

        with transaction.atomic():
            deleted_games, _ = Game.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f"Removed {deleted_games} existing games before refresh.")
            )

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

                    home_team, _ = Team.objects.update_or_create(
                        mlb_id=home_data["id"],
                        defaults={"name": home_data["name"]}
                    )

                    away_team, _ = Team.objects.update_or_create(
                        mlb_id=away_data["id"],
                        defaults={"name": away_data["name"]}
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
