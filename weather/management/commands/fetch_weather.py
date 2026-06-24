import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from games.models import Game
from weather.models import WeatherData
from weather.services import (
    STADIUM_COORDS,
    PARK_CF_BEARING,
    get_forecast,
    wind_relative_to_park,
)
from games.services.dates import eastern_today

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch rain probability for today's and upcoming games and store in DB"

    def handle(self, *args, **kwargs):
        now = timezone.now()  # UTC-aware; compared against start_time_utc below
        today = eastern_today()  # day floor follows the Eastern baseball calendar
        games = Game.objects.select_related("home_team").filter(date__gte=today)
        updated = 0

        for game in games:
            coords = STADIUM_COORDS.get(game.home_team.mlb_id)

            if not coords:
                logger.warning(f"No stadium coords for {game.home_team.name} (mlb_id={game.home_team.mlb_id})")
                continue

            lat, lon, has_roof = coords
            game_started = game.start_time_utc and game.start_time_utc < now

            if game_started:
                # Preserve existing rain_pct; only ensure has_roof is set
                obj, created = WeatherData.objects.get_or_create(
                    game=game,
                    defaults={"rain_pct": None, "has_roof": has_roof},
                )
                if not created and obj.has_roof != has_roof:
                    obj.has_roof = has_roof
                    obj.save(update_fields=["has_roof"])
            else:
                rain_pct = None
                wind_mph = None
                wind_dir = None
                wind_relative = None
                if not has_roof and game.start_time_utc:
                    forecast = get_forecast(lat, lon, game.start_time_utc)
                    if forecast:
                        rain_pct = forecast["rain_pct"]
                        wind_mph = forecast["wind_mph"]
                        wind_dir = forecast["wind_from"]
                        wind_relative = wind_relative_to_park(
                            PARK_CF_BEARING.get(game.home_team.mlb_id), wind_dir
                        )
                    self.stdout.write(
                        f"  {game} | start_utc={game.start_time_utc} | "
                        f"rain_pct={rain_pct} | wind={wind_mph}mph {wind_dir} ({wind_relative})"
                    )

                WeatherData.objects.update_or_create(
                    game=game,
                    defaults={
                        "rain_pct": rain_pct,
                        "has_roof": has_roof,
                        "wind_mph": wind_mph,
                        "wind_dir": wind_dir,
                        "wind_relative": wind_relative,
                    },
                )

            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Fetched weather for {updated} games."))
