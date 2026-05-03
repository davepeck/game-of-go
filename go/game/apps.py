"""Django AppConfig for the ``game`` app."""

from django.apps import AppConfig


class GameConfig(AppConfig):
    """App configuration for ``go.game``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "go.game"
    label = "game"
    verbose_name = "Game of Go"
