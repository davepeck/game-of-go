#!/usr/bin/env python
"""
Direct Cloud Datastore export to JSONL.

Talks gRPC straight to Cloud Datastore using ``google-cloud-datastore`` —
no App Engine in the loop, so the F1 memory ceiling and the dead Python 2
runtime are both moot. Reads each ``Game`` / ``Player`` entity, unpickles
the legacy ``current_state`` / ``history`` / ``chat_history`` blobs with a
small Py3-compat shim, and writes one JSON entity per line. The output
drops straight into ``manage.py import_from_datastore``.

Auth
    Uses Application Default Credentials. One-time setup:

        gcloud auth application-default login

    then make sure your gcloud account has Datastore read access on the
    target project (typically: project owner, or roles/datastore.viewer).

Usage
    uv run --group export scripts/export_from_datastore.py \\
        --project davepeck-go-hrd \\
        --out ./export-$(date +%Y-%m-%d)

    # Test with a small sample first:
    uv run --group export scripts/export_from_datastore.py \\
        --project davepeck-go-hrd \\
        --out ./export-sample \\
        --limit 50
"""

import argparse
import json
import sys
import typing as t
from pathlib import Path

# Add the repo root to sys.path so `from go.game import game_logic` works
# when this script is run via `uv run`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud import datastore
from google.cloud.datastore import Entity

from go.game import game_logic, legacy

_unpickle = legacy.load


# ---------------------------------------------------------------------------
# Entity → JSONable shape (matches the HTTP exporter's output)
# ---------------------------------------------------------------------------


def _iso(v: t.Any) -> str | None:
    """Return ``v.isoformat()`` if ``v`` is a datetime, else ``None``."""
    return v.isoformat() if v is not None else None


def _entity_id(entity: Entity) -> int:
    """Return the numeric id of a fetched entity (always set in practice)."""
    key = entity.key
    assert key is not None and key.id is not None, "fetched entity should always have a numeric id"
    return key.id


def _game_to_jsonable(entity: Entity) -> dict[str, t.Any]:
    """Convert a Datastore ``Game`` entity to the import command's shape."""
    current_state = _unpickle(entity["current_state"])
    history = [_unpickle(b) for b in entity.get("history") or []]
    chat_history = [_unpickle(b) for b in entity.get("chat_history") or []]

    return {
        "id": _entity_id(entity),
        "date_created": _iso(entity.get("date_created")),
        "date_last_moved": _iso(entity.get("date_last_moved")),
        "current_state": current_state.to_jsonable(),
        "history": [s.to_jsonable() for s in history],
        "chat_history": [c.to_jsonable() for c in chat_history],
        "black_cookie": entity.get("black_cookie"),
        "white_cookie": entity.get("white_cookie"),
        "is_finished": bool(entity.get("is_finished", False)),
        "has_scoring_data": bool(entity.get("has_scoring_data", False)),
        "reminder_send_time": _iso(entity.get("reminder_send_time")),
    }


def _player_to_jsonable(entity: Entity) -> dict[str, t.Any]:
    """Convert a Datastore ``Player`` entity to the import command's shape."""
    game_key = entity.get("game")
    return {
        "id": _entity_id(entity),
        "game_id": game_key.id if game_key is not None else None,
        "cookie": entity.get("cookie"),
        "color": int(entity.get("color", game_logic.CONST.No_Color)),
        "name": entity.get("name"),
        "email": entity.get("email"),
        "wants_email": bool(entity.get("wants_email", True)),
        # Pass legacy twitter fields through; the import command remaps them.
        "twitter": entity.get("twitter"),
        "wants_twitter": bool(entity.get("wants_twitter", False)),
        "contact_type": entity.get("contact_type"),
        "show_grid": bool(entity.get("show_grid", False)),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _export_kind(
    client: datastore.Client,
    kind: str,
    to_jsonable: t.Callable[[Entity], dict[str, t.Any]],
    out_path: Path,
    limit: int | None,
) -> int:
    """Stream every entity of ``kind`` through ``to_jsonable`` into JSONL."""
    query = client.query(kind=kind)
    count = 0
    errors = 0
    with out_path.open("w", encoding="utf-8") as f:
        for entity in query.fetch(limit=limit):
            try:
                row = to_jsonable(entity)
            except Exception as e:
                errors += 1
                print(
                    f"  ! {kind} {entity.key.id}: {type(e).__name__}: {e}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            f.write(json.dumps(row, separators=(",", ":")))
            f.write("\n")
            count += 1
            if count % 250 == 0:
                print(f"  ... {kind}: {count} written", file=sys.stderr, flush=True)
    if errors:
        print(
            f"  WARNING: {errors} {kind} entit(y|ies) skipped due to errors.",
            file=sys.stderr,
        )
    return count


def main() -> None:
    """Parse args, open a Datastore client, export the requested kinds."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project", required=True, help="GCP project id (e.g. davepeck-go-hrd)")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory; writes games.jsonl and/or players.jsonl.",
    )
    parser.add_argument(
        "--kinds",
        default="games,players",
        help="Comma-separated subset of {games, players} (default: both).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many entities per kind (useful for sampling).",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Datastore namespace, if you use one (default: the empty namespace).",
    )
    args = parser.parse_args()

    requested = {k.strip() for k in args.kinds.split(",") if k.strip()}
    unknown = requested - {"games", "players"}
    if unknown:
        sys.exit(f"error: unknown --kinds entries: {sorted(unknown)}")

    args.out.mkdir(parents=True, exist_ok=True)
    client = datastore.Client(project=args.project, namespace=args.namespace)
    counts: dict[str, int] = {}

    if "games" in requested:
        games_path = args.out / "games.jsonl"
        print(f"Exporting Game entities to {games_path} ...", file=sys.stderr)
        counts["games"] = _export_kind(client, "Game", _game_to_jsonable, games_path, args.limit)

    if "players" in requested:
        players_path = args.out / "players.jsonl"
        print(f"Exporting Player entities to {players_path} ...", file=sys.stderr)
        counts["players"] = _export_kind(
            client, "Player", _player_to_jsonable, players_path, args.limit
        )

    print("", file=sys.stderr)
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    print(f"Done. {summary}.", file=sys.stderr)


if __name__ == "__main__":
    main()
