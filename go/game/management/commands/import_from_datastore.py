"""
``python manage.py import_from_datastore``: one-shot migration command.

Reads two JSONL files produced by the old App Engine ``/export/games/`` and
``/export/players/`` endpoints (each file is a concatenation of the ``games``
/ ``players`` arrays from paginated export responses). Rebuilds ``Game`` and
``Player`` rows, preserving the original Datastore numeric IDs as Postgres
primary keys so that all emailed cookie-based URLs keep working after cutover.

Force-migrates ``contact_type == 'twitter'`` players to ``'email'`` when an
email address is present, else to ``'none'``.

Usage:

    python manage.py import_from_datastore games.jsonl players.jsonl
"""

import json
import typing as t
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils.dateparse import parse_datetime

from ...game_logic import CONST, ChatEntry, GameState
from ...models import Game, Player


def _iter_jsonl(path: Path) -> t.Iterator[dict[str, t.Any]]:
    """Yield each non-empty JSON object from ``path`` (one per line)."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


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


class Command(BaseCommand):
    """Import games and players from the App Engine export JSONL files."""

    help = "Import games and players from the App Engine export JSONL files."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare positional arguments for the two export files."""
        parser.add_argument("games", type=Path, help="Path to games.jsonl")
        parser.add_argument("players", type=Path, help="Path to players.jsonl")

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Read both files and insert all rows in a single transaction."""
        games_path = t.cast(Path, options["games"])
        players_path = t.cast(Path, options["players"])

        if not games_path.exists():
            raise CommandError(f"{games_path}: not found")
        if not players_path.exists():
            raise CommandError(f"{players_path}: not found")

        game_count = 0
        player_count = 0
        twitter_migrated = 0

        for g in _iter_jsonl(games_path):
            date_created = _parse_dt(g["date_created"])
            date_last_moved = _parse_dt(g["date_last_moved"])
            reminder = _parse_dt(g.get("reminder_send_time"))
            if date_created is None or date_last_moved is None:
                raise CommandError(f"Game {g['id']}: missing date_created/date_last_moved")

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
                reminder_send_time=reminder,
            )
            game_count += 1

        for p in _iter_jsonl(players_path):
            contact_type = p.get("contact_type") or CONST.Email_Contact
            email = p.get("email") or None
            if contact_type == "twitter":
                contact_type = CONST.Email_Contact if email else CONST.No_Contact
                twitter_migrated += 1

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
            player_count += 1

        self.stdout.write(
            f"Imported {game_count} games, {player_count} players "
            f"(migrated {twitter_migrated} twitter → email/none)."
        )
