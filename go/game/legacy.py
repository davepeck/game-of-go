"""
One-shot helpers for migrating data out of the App Engine Datastore.

These functions exist purely to bridge the Py2/App-Engine pickle blobs
stored in ``Game.current_state``, ``Game.history``, and
``Game.chat_history`` into our Py3 :mod:`go.game.game_logic` classes. Once
the cutover is done and no more legacy pickles need reading, this module
can be deleted.

Used by :mod:`scripts.export_from_datastore` and exercised by tests under
:class:`go.game.tests.LegacyUnpickleTests`.
"""

import io
import pickle
import typing as t

from . import game_logic

_COMPAT_CLASSES: dict[str, type] = {
    "GameState": game_logic.GameState,
    "GameBoard": game_logic.GameBoard,
    "ChatEntry": game_logic.ChatEntry,
    "BoardArray": game_logic.BoardArray,
}


class CompatUnpickler(pickle.Unpickler):
    """
    Pickle Unpickler that maps legacy module paths to our Py3 classes.

    The original App Engine app pickled instances with module paths
    ``__main__.GameState`` (when run under dev_appserver) and
    ``go.GameState`` (in production). The matching classes now live in
    :mod:`go.game.game_logic`; we override :meth:`find_class` to re-route
    by bare name. Construct with ``encoding="latin-1"`` to handle the
    Py2-bytes-vs-Py3-str difference for instance ``__dict__`` strings.
    """

    def find_class(self, module: str, name: str) -> t.Any:
        """Resolve a pickled class reference, remapping legacy classes."""
        if name in _COMPAT_CLASSES:
            return _COMPAT_CLASSES[name]
        return super().find_class(module, name)


def unpickle_legacy(blob: bytes) -> t.Any:
    """Unpickle a single legacy blob into a Py3 ``game_logic`` instance."""
    return CompatUnpickler(io.BytesIO(blob), encoding="latin-1").load()


def patch_legacy(obj: t.Any) -> t.Any:
    """
    Fill in attributes that ancient pickles might be missing.

    Older ``GameBoard`` pickles (v0/v1/v2 in the original code's
    versioning) lack one or more of ``_version`` / ``_komi_index`` /
    ``_has_owners`` / ``owners``. The original Py2 ``to_jsonable`` shielded
    against this with try/except guards; our Py3 port assumes the current
    schema, so we backfill the defaults here so ``to_jsonable`` succeeds.

    Same story for older ``GameState`` instances and the scoring fields.
    Returns the same object for convenience.
    """
    if isinstance(obj, game_logic.GameBoard):
        d = obj.__dict__
        d.setdefault("_version", 0)
        d.setdefault(
            "_komi_index",
            game_logic.CONST.Komi_None if d.get("handicap_index", 0) else 0,
        )
        d.setdefault("_has_owners", False)
        if "owners" not in d:
            d["owners"] = [[game_logic.CONST.No_Color] * d["height"] for _ in range(d["width"])]
    elif isinstance(obj, game_logic.GameState):
        d = obj.__dict__
        d.setdefault("scoring_number", -1)
        d.setdefault("white_territory", 0)
        d.setdefault("black_territory", 0)
        d.setdefault("winner", game_logic.CONST.No_Color)
        d.setdefault("black_done_number", -1)
        d.setdefault("white_done_number", -1)
        d.setdefault("last_move", (-1, -1))
        d.setdefault("last_move_was_pass", False)
        if obj.board is not None:
            patch_legacy(obj.board)
    return obj


def load(blob: bytes) -> t.Any:
    """Unpickle and patch a legacy blob in one call (the usual entry point)."""
    return patch_legacy(unpickle_legacy(blob))
