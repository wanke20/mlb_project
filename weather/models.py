from django.db import models
from games.models import Game


class WeatherData(models.Model):
    game = models.OneToOneField(Game, on_delete=models.CASCADE, related_name="weather")
    rain_pct = models.IntegerField(null=True, blank=True)
    has_roof = models.BooleanField(default=False)
    wind_mph = models.IntegerField(null=True, blank=True)
    wind_dir = models.CharField(max_length=4, null=True, blank=True)       # cardinal wind comes FROM, e.g. "NW"
    wind_relative = models.CharField(max_length=20, null=True, blank=True)  # vs. home plate, e.g. "Out to CF"
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.game} — {self.rain_pct}%"
