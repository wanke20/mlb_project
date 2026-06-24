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
    throws = models.CharField(max_length=1, null=True, blank=True)  # 'L', 'R', 'S'
    era = models.FloatField(null=True, blank=True)
    whip = models.FloatField(null=True, blank=True)
    strikeouts = models.IntegerField(null=True, blank=True)
    walks = models.IntegerField(null=True, blank=True)
    innings_pitched = models.CharField(max_length=16, null=True, blank=True)

    # Advanced metrics: FIP and K-BB% computed locally from statsapi;
    # wOBA, xERA, xwOBA, barrel% from Baseball Savant CSV leaderboards.
    fip = models.FloatField(null=True, blank=True)
    k_bb_pct = models.FloatField(null=True, blank=True)
    woba = models.FloatField(null=True, blank=True)
    xera = models.FloatField(null=True, blank=True)
    xwoba = models.FloatField(null=True, blank=True)
    barrel_pct = models.FloatField(null=True, blank=True)

    # Pitching splits — opponent AVG / OPS against, with batters faced as the
    # sample size. Pulled from the statSplits hydration (sitCodes vl/vr/h/a).
    # AVG/OPS are stored as MLB-style strings (e.g. ".220").
    vs_l_avg = models.CharField(max_length=8, null=True, blank=True)
    vs_l_ops = models.CharField(max_length=8, null=True, blank=True)
    vs_l_bf = models.IntegerField(null=True, blank=True)

    vs_r_avg = models.CharField(max_length=8, null=True, blank=True)
    vs_r_ops = models.CharField(max_length=8, null=True, blank=True)
    vs_r_bf = models.IntegerField(null=True, blank=True)

    home_avg = models.CharField(max_length=8, null=True, blank=True)
    home_ops = models.CharField(max_length=8, null=True, blank=True)
    home_bf = models.IntegerField(null=True, blank=True)

    away_avg = models.CharField(max_length=8, null=True, blank=True)
    away_ops = models.CharField(max_length=8, null=True, blank=True)
    away_bf = models.IntegerField(null=True, blank=True)

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

    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    home_starter_runs = models.IntegerField(null=True, blank=True)
    away_starter_runs = models.IntegerField(null=True, blank=True)
    home_starter_innings = models.CharField(max_length=8, null=True, blank=True)
    away_starter_innings = models.CharField(max_length=8, null=True, blank=True)

    def __str__(self):
        return f"{self.away_team} @ {self.home_team}"


class Hitter(models.Model):
    mlb_id = models.IntegerField()
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='hitters')
    # A team's lineup differs by day, so hitters are stored per date. The same
    # player can appear for the same team on multiple dates (one row each).
    date = models.DateField(null=True, blank=True)
    bats = models.CharField(max_length=1, null=True, blank=True)  # 'L', 'R', 'S'
    rank = models.IntegerField(null=True, blank=True)  # 1..N within team, by lineup spot
    position = models.CharField(max_length=8, null=True, blank=True)  # 'SS', 'DH', '1B', ...

    season_pa = models.IntegerField(null=True, blank=True)
    season_avg = models.CharField(max_length=8, null=True, blank=True)
    season_ops = models.CharField(max_length=8, null=True, blank=True)

    vs_l_pa = models.IntegerField(null=True, blank=True)
    vs_l_avg = models.CharField(max_length=8, null=True, blank=True)
    vs_l_ops = models.CharField(max_length=8, null=True, blank=True)

    vs_r_pa = models.IntegerField(null=True, blank=True)
    vs_r_avg = models.CharField(max_length=8, null=True, blank=True)
    vs_r_ops = models.CharField(max_length=8, null=True, blank=True)

    class Meta:
        ordering = ['rank']
        unique_together = [('mlb_id', 'date')]

    def __str__(self):
        return self.name


class Reliever(models.Model):
    mlb_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='relievers')
    season_appearances = models.IntegerField(default=0)
    saves = models.IntegerField(default=0)
    holds = models.IntegerField(default=0)
    era = models.FloatField(null=True, blank=True)
    pitched_yesterday = models.BooleanField(default=False)
    yesterday_pitches = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-season_appearances']

    def __str__(self):
        return self.name


class PlayerIDMap(models.Model):
    """Persistent name -> MLBAM id crosswalk.

    Projected-lineup sources (RotoWire, Baseball Press) give player names, not
    MLBAM ids. Resolving a name against the team roster is fuzzy and costs an
    API call, so we cache the result here. This table is NOT wiped by the
    fetch_games hitter refresh, so it survives across runs and accumulates
    resolved players (including bench/platoon bats not in the top-6).

    Keyed by (normalized_name, team): a player traded mid-season simply gets a
    new row under their new team.
    """
    normalized_name = models.CharField(max_length=100)  # lowercased, accent-stripped
    name = models.CharField(max_length=100)  # original display name, for debugging
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='player_ids')
    mlb_id = models.IntegerField()
    bats = models.CharField(max_length=1, null=True, blank=True)  # 'L', 'R', 'S'
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('normalized_name', 'team')]

    def __str__(self):
        return f"{self.name} ({self.mlb_id})"
