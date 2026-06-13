from django.contrib import admin

from .models import Pick


@admin.register(Pick)
class PickAdmin(admin.ModelAdmin):
    list_display = ("user", "game", "picked_team", "status", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__username", "picked_team__name")
    autocomplete_fields = ()
    raw_id_fields = ("user", "game", "picked_team")
