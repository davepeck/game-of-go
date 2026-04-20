"""
Django ORM models for Game and Player.

Numeric ``id`` values come from the old App Engine Datastore and are preserved
across the migration so that emailed URLs (which are keyed by player cookie,
but the admin/debug paths use the numeric id) remain stable. Cookies are the
only user-facing identifier and are what the web routes match on.
"""

from django.db import models


class Game(models.Model):
    """A single game of Go between two players, JSON-serialized game state."""

    # Datastore numeric id preserved as PK.
    id = models.BigIntegerField(primary_key=True)
    date_created = models.DateTimeField()
    date_last_moved = models.DateTimeField()

    # GameState.to_jsonable() shape. See go.game.game_logic.GameState.
    current_state = models.JSONField()
    # Array of GameState.to_jsonable(), one entry per committed move.
    history = models.JSONField(default=list)
    # Array of ChatEntry.to_jsonable().
    chat_history = models.JSONField(default=list)

    black_cookie = models.CharField(max_length=64, null=True, blank=True)
    white_cookie = models.CharField(max_length=64, null=True, blank=True)

    is_finished = models.BooleanField(default=False)
    has_scoring_data = models.BooleanField(default=False)
    reminder_send_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Index ``reminder_send_time`` only for in-progress games."""

        indexes = [
            models.Index(
                fields=["reminder_send_time"],
                name="game_reminder_idx",
                condition=models.Q(is_finished=False),
            ),
        ]

    def __str__(self) -> str:
        """Return a human-readable label for admin listings."""
        return f"Game #{self.id}"


class Player(models.Model):
    """One of the two players in a Game, identified by a random cookie."""

    id = models.BigIntegerField(primary_key=True)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="players")
    cookie = models.CharField(max_length=64, unique=True, db_index=True)
    color = models.IntegerField(default=0)
    name = models.CharField(max_length=200, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    wants_email = models.BooleanField(default=True)
    # 'email' or 'none'. Twitter is gone; imports remap 'twitter' to 'email'
    # when an email exists, else 'none'.
    contact_type = models.CharField(max_length=16, default="email")
    show_grid = models.BooleanField(default=False)

    def __str__(self) -> str:
        """Return a human-readable label for admin listings."""
        return f"Player #{self.id} ({self.cookie})"
