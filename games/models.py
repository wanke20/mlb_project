from django.db import models

class Team(models.Model):
    name = models.CharField(max_length=100)
    mlb_id = models.IntegerField(unique=True)
    wins = models.IntegerField(null=True, blank=True)
    losses = models.IntegerField(null=True, blank=True)
    win_pct = models.FloatField(null=True, blank=True)
    last10_wins = models.IntegerField(default=0)
    last10_losses = models.IntegerField(default=0)

    abbreviation = models.CharField(max_length=5, null=True, blank=True)

    # Streak
    streak_type = models.CharField(max_length=1, null=True, blank=True)  # 'W' or 'L'
    streak_length = models.IntegerField(null=True, blank=True)

    # Last 7 days hitting
    last7_avg = models.CharField(max_length=8, null=True, blank=True)
    last7_runs = models.IntegerField(null=True, blank=True)

    # Season hitting
    season_avg = models.CharField(max_length=8, null=True, blank=True)
    season_ops = models.CharField(max_length=8, null=True, blank=True)
    season_runs = models.IntegerField(null=True, blank=True)
    season_strikeouts = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name


class Pitcher(models.Model):
    name = models.CharField(max_length=100)
    mlb_id = models.IntegerField(unique=True)
    era = models.FloatField(null=True, blank=True)
    whip = models.FloatField(null=True, blank=True)
    strikeouts = models.IntegerField(null=True, blank=True)
    walks = models.IntegerField(null=True, blank=True)
    innings_pitched = models.CharField(max_length=16, null=True, blank=True)

    def __str__(self):
        return self.name


class Game(models.Model):
    game_id = models.IntegerField(unique=True)
    date = models.DateField()
    start_time_utc = models.DateTimeField(null=True, blank=True)

    home_team = models.ForeignKey(Team, related_name="home_games", on_delete=models.CASCADE)
    away_team = models.ForeignKey(Team, related_name="away_games", on_delete=models.CASCADE)

    home_pitcher = models.ForeignKey(Pitcher, related_name="home_starts", null=True, blank=True, on_delete=models.SET_NULL)
    away_pitcher = models.ForeignKey(Pitcher, related_name="away_starts", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.away_team} @ {self.home_team}"
