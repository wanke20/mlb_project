from django.contrib import admin
from .models import Team, Pitcher, Game


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "mlb_id")


@admin.register(Pitcher)
class PitcherAdmin(admin.ModelAdmin):
    list_display = ("name", "mlb_id", "era")


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        "game_id",
        "date",
        "away_team",
        "home_team",
        "away_pitcher",
        "home_pitcher",
    )
    list_filter = ("date",)
    search_fields = ("home_team__name", "away_team__name")