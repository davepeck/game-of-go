#!/usr/bin/env python
"""
Paginated export of Game and Player entities from the live App Engine app.

Paginates the existing ``/export/games/`` and ``/export/players/`` handlers
in the still-live App Engine deployment and writes one entity per line
(JSONL) to an output directory. The handlers already unpickle state/chat
blobs via ``to_jsonable()``, so this script only has to walk the pages and
append each row to its file.

Feed the output into ``python manage.py import_from_datastore`` on the new
dokku/Postgres side.

Auth
    The ``/export/*`` routes are gated by App Engine ``login: admin``. Provide
    exactly one of:

    - ``--cookie "<full cookie header value>"`` (or ``APPENGINE_COOKIE`` env
      var): grab from browser devtools after logging into the live app as a
      Google admin. Works for standard App Engine auth.
    - ``--bearer <token>`` (or ``APPENGINE_BEARER`` env var): sends
      ``Authorization: Bearer <token>``; works when the app is fronted by
      Identity-Aware Proxy. Not used for the default setup.

Usage
    APPENGINE_COOKIE='SACSID=...; ACSID=...' \\
        uv run scripts/export_from_appengine.py \\
        --base-url https://go.davepeck.org \\
        --out ./export-$(date +%Y-%m-%d)
"""

import argparse
import json
import os
import sys
import typing as t
from pathlib import Path

import requests


def _auth_headers(cookie: str | None, bearer: str | None) -> dict[str, str]:
    """Return an auth header dict, or exit with a clear error if neither given."""
    if bearer and cookie:
        sys.exit("error: pass only one of --cookie / --bearer")
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}
    if cookie:
        return {"Cookie": cookie}
    sys.exit(
        "error: missing auth. Set APPENGINE_COOKIE env var (or --cookie) "
        "using a session cookie from browser devtools, or set APPENGINE_BEARER "
        "(or --bearer) with an IAP identity token."
    )


def _paginate(
    session: requests.Session,
    base_url: str,
    path: str,
    field: str,
    out: t.IO[str],
    page_size: int,
    resume_from: int = 0,
) -> int:
    """
    Paginate ``path`` (one of ``/export/games/``, ``/export/players/``) into JSONL.

    Returns the total number of rows written in this run. If ``resume_from``
    is non-zero, pagination starts after that id (letting you continue after
    a crash or Ctrl-C without rewriting already-saved rows).
    """
    last_id_seen = resume_from
    total = 0
    while True:
        url = f"{base_url.rstrip('/')}{path}"
        r = session.get(
            url,
            params={"last_id_seen": str(last_id_seen), "amount": str(page_size)},
            timeout=60,
        )
        r.raise_for_status()
        payload = r.json()
        rows = payload.get(field, [])
        if not rows:
            return total
        for row in rows:
            out.write(json.dumps(row, separators=(",", ":")))
            out.write("\n")
        total += len(rows)
        next_id = payload.get("last_id_seen", 0)
        print(
            f"  {field}: {total} written (last_id_seen={next_id})",
            file=sys.stderr,
            flush=True,
        )
        # The handler returns ``last_id_seen: 0`` when the page was empty,
        # and repeats the same id when we've walked off the end. Either
        # means we're done.
        if not next_id or next_id == last_id_seen:
            return total
        last_id_seen = next_id


def main() -> None:
    """Parse args, authenticate, and paginate both export endpoints to JSONL."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Root URL of the live App Engine deployment (e.g. https://go.davepeck.org).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory (created if missing). Writes games.jsonl and players.jsonl.",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("APPENGINE_COOKIE"),
        help="Full Cookie header value (from browser devtools after admin login).",
    )
    parser.add_argument(
        "--bearer",
        default=os.environ.get("APPENGINE_BEARER"),
        help="Bearer token (IAP identity token).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="Rows per page request (default: 500). App Engine request timeout is 60s.",
    )
    parser.add_argument(
        "--kinds",
        default="games,players",
        help=(
            "Comma-separated subset of {games, players} to export "
            "(default: both). Useful when one half finished and the other "
            "didn't."
        ),
    )
    parser.add_argument(
        "--resume-from-games",
        type=int,
        default=0,
        help="Start games pagination after this Datastore id (skip rows already on disk).",
    )
    parser.add_argument(
        "--resume-from-players",
        type=int,
        default=0,
        help="Start players pagination after this Datastore id.",
    )
    args = parser.parse_args()

    requested_kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    unknown = requested_kinds - {"games", "players"}
    if unknown:
        sys.exit(f"error: unknown --kinds entries: {sorted(unknown)}")

    args.out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(_auth_headers(args.cookie, args.bearer))

    counts: dict[str, int] = {}

    if "games" in requested_kinds:
        games_path: Path = args.out / "games.jsonl"
        mode = "a" if args.resume_from_games else "w"
        print(
            f"Exporting games to {games_path} (mode={mode!r}, "
            f"resume_from={args.resume_from_games}) ...",
            file=sys.stderr,
        )
        with games_path.open(mode, encoding="utf-8") as f:
            counts["games"] = _paginate(
                session,
                args.base_url,
                "/export/games/",
                "games",
                f,
                args.page_size,
                resume_from=args.resume_from_games,
            )

    if "players" in requested_kinds:
        players_path: Path = args.out / "players.jsonl"
        mode = "a" if args.resume_from_players else "w"
        print(
            f"Exporting players to {players_path} (mode={mode!r}, "
            f"resume_from={args.resume_from_players}) ...",
            file=sys.stderr,
        )
        with players_path.open(mode, encoding="utf-8") as f:
            counts["players"] = _paginate(
                session,
                args.base_url,
                "/export/players/",
                "players",
                f,
                args.page_size,
                resume_from=args.resume_from_players,
            )

    print("", file=sys.stderr)
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    print(f"Done. {summary} written this run.", file=sys.stderr)
    print(
        "\nNext: compare these counts against the Datastore entity counts in the "
        "GCP console, then feed the JSONL files into ``python manage.py "
        "import_from_datastore``.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
