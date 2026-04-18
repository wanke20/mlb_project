from django.db import models
from games.models import Game


class WeatherData(models.Model):
    game = models.OneToOneField(Game, on_delete=models.CASCADE, related_name="weather")
    rain_pct = models.IntegerField(null=True, blank=True)
    has_roof = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.game} — {self.rain_pct}%"
