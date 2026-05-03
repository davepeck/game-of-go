"""
Django ORM models for Game and Player.

Numeric ``id`` values come from the old App Engine Datastore and are preserved
across the migration so that emailed URLs (which are keyed by player cookie,
but the admin/debug paths use the numeric id) remain stable. Cookies are the
only user-facing identifier and are what the web routes match on.

Django's ORM uses descriptors, which confuses ``ty`` (no Django-stubs support
yet): at the class level ``self.some_field`` looks like the ``Field`` instance
to the type checker, but Django's descriptor protocol converts it to the
Python value at instance level. We bridge with ``t.Any`` annotations on the
field attributes — Django ignores the annotations, and ty stops conflating the
descriptor type with the stored value's type. Helper methods return concrete
types for the rest of the codebase.
"""

import typing as t
from datetime import UTC, datetime, timedelta

from django.db import models

from . import game_logic as gl


class Game(models.Model):
    """A single game of Go between two players, JSON-serialized game state."""

    objects: models.Manager[Game]

    # Datastore numeric id preserved as PK during import. ``BigAutoField``
    # auto-increments for new games and accepts an explicit id for imports.
    id: t.Any = models.BigAutoField(primary_key=True)
    date_created: t.Any = models.DateTimeField()
    date_last_moved: t.Any = models.DateTimeField()

    # GameState.to_jsonable() shape. See go.game.game_logic.GameState.
    current_state: t.Any = models.JSONField()
    # Array of GameState.to_jsonable(), one entry per committed move.
    history: t.Any = models.JSONField(default=list)
    # Array of ChatEntry.to_jsonable().
    chat_history: t.Any = models.JSONField(default=list)

    black_cookie: t.Any = models.CharField(max_length=64, null=True, blank=True)
    white_cookie: t.Any = models.CharField(max_length=64, null=True, blank=True)

    is_finished: t.Any = models.BooleanField(default=False)
    has_scoring_data: t.Any = models.BooleanField(default=False)
    reminder_send_time: t.Any = models.DateTimeField(null=True, blank=True)

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

    # ---- game-state helpers ----

    def load_state(self) -> gl.GameState:
        """Return the current ``GameState`` freshly reconstructed from JSON."""
        return gl.GameState.from_jsonable(self.current_state)

    def save_state(self, state: gl.GameState) -> None:
        """Persist ``state`` back into ``current_state`` (caller must ``save()``)."""
        self.current_state = state.to_jsonable()

    def load_history_state(self, move_number: int) -> gl.GameState:
        """Return the historical ``GameState`` at ``move_number``."""
        return gl.GameState.from_jsonable(self.history[move_number])

    def append_history(self, state: gl.GameState) -> None:
        """Append ``state`` as a new entry in the history log."""
        self.history = [*self.history, state.to_jsonable()]

    def load_chat(self) -> list[gl.ChatEntry]:
        """Return all chat entries reconstructed from JSON."""
        return [gl.ChatEntry.from_jsonable(e) for e in self.chat_history]

    def append_chat(self, entry: gl.ChatEntry) -> None:
        """Append ``entry`` to the chat log."""
        self.chat_history = [*self.chat_history, entry.to_jsonable()]

    # ---- progress helpers ----

    def get_current_move_number(self) -> int:
        """Return the current 0-based move number (equals ``len(history)``)."""
        return len(self.history)

    def in_progress(self) -> bool:
        """Return ``True`` if the game is live and not finished or scoring."""
        return bool(not self.has_scoring_data and not self.is_finished)

    def is_scoring(self) -> bool:
        """Return ``True`` if the game is in the scoring phase."""
        return bool(self.has_scoring_data and not self.is_finished)

    def dont_remind_for_long_time(self) -> None:
        """Push ``reminder_send_time`` far into the future and save."""
        self.reminder_send_time = datetime.now(UTC) + timedelta(weeks=52)
        self.save(update_fields=["reminder_send_time"])

    # ---- player lookup ----

    def get_black_player(self) -> Player | None:
        """Return the Black player, or ``None`` if not found."""
        return Player.objects.filter(cookie=self.black_cookie).first()

    def get_white_player(self) -> Player | None:
        """Return the White player, or ``None`` if not found."""
        return Player.objects.filter(cookie=self.white_cookie).first()

    def get_player_whose_move(self) -> Player | None:
        """Return the player whose turn it is, or ``None`` if the game is over."""
        if self.is_finished or self.has_scoring_data:
            return None
        state = self.load_state()
        if state.get_whose_move() == gl.CONST.Black_Color:
            return self.get_black_player()
        return self.get_white_player()

    def get_black_friendly_name(self) -> str:
        """Return the Black player's display name (empty string if missing)."""
        p = self.get_black_player()
        return p.get_friendly_name() if p else ""

    def get_white_friendly_name(self) -> str:
        """Return the White player's display name (empty string if missing)."""
        p = self.get_white_player()
        return p.get_friendly_name() if p else ""


class Player(models.Model):
    """One of the two players in a Game, identified by a random cookie."""

    objects: models.Manager[Player]

    id: t.Any = models.BigAutoField(primary_key=True)
    game: t.Any = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="players")
    cookie: t.Any = models.CharField(max_length=64, unique=True, db_index=True)
    color: t.Any = models.IntegerField(default=0)
    name: t.Any = models.CharField(max_length=200, null=True, blank=True)
    email: t.Any = models.EmailField(null=True, blank=True)
    wants_email: t.Any = models.BooleanField(default=True)
    # 'email' or 'none'. Twitter is gone; imports remap 'twitter' to 'email'
    # when an email exists, else 'none'.
    contact_type: t.Any = models.CharField(max_length=16, default="email")
    show_grid: t.Any = models.BooleanField(default=False)

    def __str__(self) -> str:
        """Return a human-readable label for admin listings."""
        return f"Player #{self.id} ({self.cookie})"

    @classmethod
    def by_cookie(cls, cookie: str) -> Player | None:
        """Return the Player with the given cookie, or ``None``."""
        return cls.objects.filter(cookie=cookie).select_related("game").first()

    def get_friendly_name(self) -> str:
        """Return a short display name (strip email domain, truncate to 18)."""
        friendly: str = self.name or ""
        at_loc = friendly.find("@")
        if at_loc != -1:
            friendly = friendly[:at_loc]
        if len(friendly) > 18:
            friendly = friendly[:15] + "..."
        return friendly

    def get_opponent(self) -> Player | None:
        """Return the opposing player in the same game, or ``None``."""
        other = gl.opposite_color(self.color)
        game: Game = self.game
        if other == gl.CONST.Black_Color:
            return game.get_black_player()
        return game.get_white_player()

    def get_contact_type(self) -> str:
        """Return the player's contact type (defaults to 'email')."""
        return self.contact_type or gl.CONST.Email_Contact

    def get_active_contact_type(self) -> str:
        """Return the active contact type: 'email' if opted in, else 'none'."""
        return gl.CONST.Email_Contact if self.wants_email else gl.CONST.No_Contact

    def get_contact(self) -> str:
        """Return the player's contact value (always the email address)."""
        return self.email or ""

    def get_safe_email(self) -> str:
        """Return the email address or an empty string if unset."""
        return self.email or ""
