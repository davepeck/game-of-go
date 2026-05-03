"""
Django admin registration for Game and Player.

Gives a GUI for: looking up games by cookie, inspecting ``current_state`` JSON,
hand-fixing stuck games, nudging ``reminder_send_time``. Replaces the ad-hoc
admin tooling from the old App Engine app.
"""

from django.contrib import admin

from .models import Game, Player


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    """Admin configuration for Game."""

    list_display = (
        "id",
        "date_last_moved",
        "is_finished",
        "has_scoring_data",
        "reminder_send_time",
    )
    list_filter = ("is_finished", "has_scoring_data")
    search_fields = ("black_cookie", "white_cookie")
    readonly_fields = ("current_state", "history", "chat_history")
    date_hierarchy = "date_last_moved"


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    """Admin configuration for Player."""

    list_display = (
        "id",
        "cookie",
        "name",
        "email",
        "color",
        "contact_type",
        "wants_email",
    )
    search_fields = ("cookie", "email", "name")
    list_filter = ("contact_type", "wants_email")
    raw_id_fields = ("game",)
