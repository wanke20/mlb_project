from django.core.management.base import BaseCommand
from games.models import Game
from weather.models import WeatherData
from weather.services import STADIUM_COORDS, get_rain_probability

import logging
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch rain probability for today's games and store in DB"

    def handle(self, *args, **kwargs):
        games = Game.objects.select_related("home_team").all()
        updated = 0

        for game in games:
            coords = STADIUM_COORDS.get(game.home_team.mlb_id)

            if not coords:
                logger.warning(f"No stadium coords for {game.home_team.name} (mlb_id={game.home_team.mlb_id})")
                continue

            lat, lon, has_roof = coords

            rain_pct = None
            if not has_roof and game.start_time_utc:
                rain_pct = get_rain_probability(lat, lon, game.start_time_utc)
                self.stdout.write(f"  {game} | start_utc={game.start_time_utc} | rain_pct={rain_pct}")

            WeatherData.objects.update_or_create(
                game=game,
                defaults={
                    "rain_pct": rain_pct,
                    "has_roof": has_roof,
                },
            )
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Fetched weather for {updated} games."))
