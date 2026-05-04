"""
Django admin registration for Game and Player.

Gives a GUI for: looking up games by cookie, inspecting ``current_state`` JSON,
hand-fixing stuck games, nudging ``reminder_send_time``. Replaces the ad-hoc
admin tooling from the old App Engine app.
"""

from datetime import UTC, datetime, timedelta

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from .models import Game, Player

_ACTIVE_WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class ActiveWithinFilter(admin.SimpleListFilter):
    """Filter unfinished games by recency of the last move."""

    title = "active within"
    parameter_name = "active_within"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        """Return the available ``active within`` window choices."""
        return [
            ("1h", "Last hour"),
            ("24h", "Last 24 hours"),
            ("7d", "Last week"),
            ("30d", "Last 30 days"),
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Game]) -> QuerySet[Game] | None:
        """Restrict ``queryset`` to unfinished games moved within the chosen window."""
        value = self.value()
        if value is None:
            return queryset
        delta = _ACTIVE_WINDOWS.get(value)
        if delta is None:
            return queryset
        cutoff = datetime.now(UTC) - delta
        return queryset.filter(is_finished=False, date_last_moved__gte=cutoff)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    """Admin configuration for Game."""

    list_display = (
        "date_last_moved",
        "black_cookie_link",
        "white_cookie_link",
        "is_finished",
        "has_scoring_data",
        "reminder_send_time",
    )
    list_filter = (ActiveWithinFilter, "is_finished", "has_scoring_data")
    search_fields = ("black_cookie", "white_cookie")
    readonly_fields = ("current_state", "history", "chat_history")
    date_hierarchy = "date_last_moved"

    @admin.display(description="Black", ordering="black_cookie")
    def black_cookie_link(self, obj: Game) -> str:
        """Render the Black player's cookie as a link to the play view."""
        return _play_link(obj.black_cookie)

    @admin.display(description="White", ordering="white_cookie")
    def white_cookie_link(self, obj: Game) -> str:
        """Render the White player's cookie as a link to the play view."""
        return _play_link(obj.white_cookie)


def _play_link(cookie: str | None) -> str:
    """Return an HTML anchor to the play view for ``cookie`` (empty if missing)."""
    if not cookie:
        return ""
    url = reverse("play", kwargs={"cookie": cookie})
    return format_html('<a href="{}">{}</a>', url, cookie)


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
