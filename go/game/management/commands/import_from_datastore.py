"""
``python manage.py import_from_datastore``: one-shot migration command.

Reads the JSONL files produced by ``scripts/export_from_appengine.py``
(one entity per line, from the still-live App Engine ``/export/*``
endpoints). Rebuilds ``Game`` and ``Player`` rows, preserving the original
Datastore numeric IDs as Postgres primary keys so every emailed cookie URL
keeps working after cutover.

What this command guarantees before committing:

1. Every input row has the fields we need (``id``, dates, cookies, etc.).
2. Every state/chat blob round-trips through ``from_jsonable``.
3. No duplicate player cookies in the input.
4. Every ``player.game_id`` refers to a game we just inserted.
5. Every imported game ends up with exactly two players.
6. Each player's ``cookie`` matches its game's ``black_cookie`` or
   ``white_cookie`` and its ``color`` agrees.
7. Every in-progress (not-finished) game has a non-null
   ``reminder_send_time`` — protects against a post-cutover reminder flood.
8. ``contact_type == 'twitter'`` migrated to ``'email'`` (if email present)
   or ``'none'``. Twitter is gone.
9. On Postgres, the ``BigAutoField`` sequence is bumped past the max
   imported id so future new games don't PK-collide.

All of the above runs inside a single ``transaction.atomic`` block. Any
failure rolls the whole import back. ``--dry-run`` rolls back on success
too, for rehearsals.

Usage:

    python manage.py import_from_datastore games.jsonl players.jsonl
    python manage.py import_from_datastore games.jsonl players.jsonl --dry-run
"""

import json
import typing as t
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from ...game_logic import CONST, ChatEntry, GameState
from ...models import Game, Player

_REQUIRED_GAME_FIELDS = ("id", "date_created", "date_last_moved", "current_state")
_REQUIRED_PLAYER_FIELDS = ("id", "game_id", "cookie")


def _iter_jsonl(path: Path) -> t.Iterator[dict[str, t.Any]]:
    """Yield each non-empty JSON object from ``path`` (one per line)."""
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise CommandError(f"{path}:{line_no}: invalid JSON: {e}") from e


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an ISO timestamp (as emitted by the old export), or ``None``."""
    if raw is None:
        return None
    return parse_datetime(raw)


def _normalize_game_state(raw: dict[str, t.Any]) -> dict[str, t.Any]:
    """Round-trip a state dict through ``GameState`` to enforce current shape."""
    return GameState.from_jsonable(raw).to_jsonable()


def _normalize_chat(raw: dict[str, t.Any]) -> dict[str, t.Any]:
    """Round-trip a chat entry through ``ChatEntry`` to enforce current shape."""
    return ChatEntry.from_jsonable(raw).to_jsonable()


def _require_fields(row: dict[str, t.Any], fields: tuple[str, ...], what: str) -> None:
    """Raise ``CommandError`` if any of ``fields`` is missing from ``row``."""
    missing = [f for f in fields if f not in row]
    if missing:
        raise CommandError(f"{what}: missing required fields {missing}: {row!r}")


class Command(BaseCommand):
    """Import games and players from the App Engine export JSONL files."""

    help = "Import games and players from the App Engine export JSONL files."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare positional file args and the ``--dry-run`` flag."""
        parser.add_argument("games", type=Path, help="Path to games.jsonl")
        parser.add_argument("players", type=Path, help="Path to players.jsonl")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the whole import inside a transaction then roll back.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Read both files and insert all rows in a single transaction."""
        games_path = t.cast(Path, options["games"])
        players_path = t.cast(Path, options["players"])
        dry_run = bool(options.get("dry_run"))

        if not games_path.exists():
            raise CommandError(f"{games_path}: not found")
        if not players_path.exists():
            raise CommandError(f"{players_path}: not found")

        with transaction.atomic():
            game_count, player_count, twitter_migrated = self._do_import(games_path, players_path)
            self._bump_sequences()
            if dry_run:
                transaction.set_rollback(True)

        tag = " (DRY RUN; rolled back)" if dry_run else ""
        self.stdout.write(
            f"Imported {game_count} games, {player_count} players "
            f"(migrated {twitter_migrated} twitter \u2192 email/none).{tag}"
        )

    # ---- core work ----

    def _do_import(self, games_path: Path, players_path: Path) -> tuple[int, int, int]:
        """Insert games then players; raise on the first integrity violation."""
        game_ids: set[int] = set()
        game_count = 0
        for g in _iter_jsonl(games_path):
            _require_fields(g, _REQUIRED_GAME_FIELDS, f"Game {g.get('id', '?')}")
            self._insert_game(g)
            game_ids.add(int(g["id"]))
            game_count += 1

        seen_cookies: set[str] = set()
        player_count = 0
        twitter_migrated = 0
        for p in _iter_jsonl(players_path):
            _require_fields(p, _REQUIRED_PLAYER_FIELDS, f"Player {p.get('id', '?')}")
            if int(p["game_id"]) not in game_ids:
                raise CommandError(
                    f"Player {p['id']}: game_id {p['game_id']} not in the imported games"
                )
            cookie = str(p["cookie"])
            if cookie in seen_cookies:
                raise CommandError(f"Player {p['id']}: duplicate cookie {cookie!r}")
            seen_cookies.add(cookie)

            twitter_migrated += self._insert_player(p)
            player_count += 1

        self._validate_post_insert()
        return game_count, player_count, twitter_migrated

    def _insert_game(self, g: dict[str, t.Any]) -> None:
        """Insert one game row after normalizing its state blobs."""
        date_created = _parse_dt(g["date_created"])
        date_last_moved = _parse_dt(g["date_last_moved"])
        if date_created is None or date_last_moved is None:
            raise CommandError(f"Game {g['id']}: unparseable date_created/date_last_moved")
        Game.objects.create(
            id=g["id"],
            date_created=date_created,
            date_last_moved=date_last_moved,
            current_state=_normalize_game_state(g["current_state"]),
            history=[_normalize_game_state(s) for s in g.get("history", [])],
            chat_history=[_normalize_chat(c) for c in g.get("chat_history", [])],
            black_cookie=g.get("black_cookie"),
            white_cookie=g.get("white_cookie"),
            is_finished=bool(g.get("is_finished", False)),
            has_scoring_data=bool(g.get("has_scoring_data", False)),
            reminder_send_time=_parse_dt(g.get("reminder_send_time")),
        )

    def _insert_player(self, p: dict[str, t.Any]) -> int:
        """Insert one player row; return 1 if a twitter->email migration happened."""
        contact_type = p.get("contact_type") or CONST.Email_Contact
        email = p.get("email") or None
        migrated = 0
        if contact_type == "twitter":
            contact_type = CONST.Email_Contact if email else CONST.No_Contact
            migrated = 1

        Player.objects.create(
            id=p["id"],
            game_id=p["game_id"],
            cookie=p["cookie"],
            color=int(p.get("color", CONST.No_Color)),
            name=p.get("name"),
            email=email,
            wants_email=bool(p.get("wants_email", True)),
            contact_type=contact_type,
            show_grid=bool(p.get("show_grid", False)),
        )
        return migrated

    # ---- validation ----

    def _validate_post_insert(self) -> None:
        """Run the cross-row integrity checks, raising on any violation."""
        self._validate_players_per_game()
        self._validate_cookie_color_consistency()
        self._validate_reminder_send_time()

    def _validate_players_per_game(self) -> None:
        """Every imported game must end up with exactly two players."""
        from django.db.models import Count

        bad = Game.objects.annotate(n=Count("players")).exclude(n=2).values_list("id", "n")[:10]
        if bad:
            raise CommandError(f"Games with !=2 players (showing up to 10): {list(bad)}")

    def _validate_cookie_color_consistency(self) -> None:
        """Each player's cookie must match one of its game's color-cookies, and color must be Black/White."""
        for player in Player.objects.all().select_related("game"):
            game = player.game
            if player.cookie not in (game.black_cookie, game.white_cookie):
                raise CommandError(
                    f"Player {player.id} (game {game.id}): cookie "
                    f"{player.cookie!r} is neither black_cookie nor white_cookie"
                )
            expected_color = (
                CONST.Black_Color if player.cookie == game.black_cookie else CONST.White_Color
            )
            if player.color != expected_color:
                raise CommandError(
                    f"Player {player.id} (game {game.id}): color "
                    f"{player.color} disagrees with expected {expected_color}"
                )

    def _validate_reminder_send_time(self) -> None:
        """In-progress games must have ``reminder_send_time`` set.

        A null value would make the cron treat the row as ancient and blast
        a 'your turn!' reminder three minutes after cutover.
        """
        missing = list(
            Game.objects.filter(is_finished=False, reminder_send_time__isnull=True).values_list(
                "id", flat=True
            )[:10]
        )
        if missing:
            raise CommandError(
                f"In-progress games missing reminder_send_time: {missing} "
                f"(showing up to 10). Aborting to avoid post-cutover reminder flood."
            )

    def _bump_sequences(self) -> None:
        """Reset Postgres PK sequences past ``max(id)`` so new games don't collide.

        ``BigAutoField`` with explicit-PK inserts leaves the backing sequence
        at its prior value; the next sequence-based insert would then collide
        with an imported row. SQLite's ``AUTOINCREMENT`` has no separate
        sequence object to bump, so this is a no-op there.
        """
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            for table in ("game_game", "game_player"):
                cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                (current_max,) = cursor.fetchone()
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)",
                    [table, max(current_max, 1)],
                )
