"""
Core game logic for Go.

Ported from www/go.py (Python 2.7 / App Engine) to Python 3 / Django.

The persistent representation of game state is JSON (stored in Postgres as
JSONB via Django's JSONField). ``to_jsonable()`` / ``from_jsonable()`` on each
class are the round-trip boundary.

No pickle, no backwards-compat attribute sniffing: objects loaded from the DB
are always at the current schema version because they are reconstructed from
JSON we fully control.
"""

import copy
import random
import string
import typing as t
from collections import deque

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class CONST:
    """Game-wide constants: colors, board sizes, handicap/komi tables, and the
    current on-disk schema version."""

    No_Color = 0
    Black_Color = 1
    White_Color = 2
    Both_Colors = 3
    Color_Names = ["none", "black", "white", "both"]
    Star_Ordinals = [[3, 9, 15], [3, 6, 9], [2, 4, 6]]
    Board_Sizes = [(19, 19), (13, 13), (9, 9)]
    Board_Classes = ["nineteen_board", "thirteen_board", "nine_board"]
    Board_Size_Names = ["19 x 19", "13 x 13", "9 x 9"]
    Handicaps = [0, 9, 8, 7, 6, 5, 4, 3, 2]
    Handicap_Names = [
        "plays first",
        "has a nine stone handicap",
        "has an eight stone handicap",
        "has a seven stone handicap",
        "has a six stone handicap",
        "has a five stone handicap",
        "has a four stone handicap",
        "has a three stone handicap",
        "has a two stone handicap",
    ]
    Handicap_Positions = [
        [(15, 3), (3, 15), (15, 15), (3, 3), (9, 9), (3, 9), (15, 9), (9, 3), (9, 15)],
        [(9, 3), (3, 9), (9, 9), (3, 3), (6, 6), (3, 6), (9, 6), (6, 3), (6, 9)],
        [(6, 2), (2, 6), (6, 6), (2, 2), (4, 4)],
    ]
    Komis = [6.5, 5.5, 0.5, -4.5, -5.5]
    Komi_Names = [
        "has six komi",
        "has five komi",
        "has no komi",
        "has five reverse komi",
        "has six reverse komi",
    ]
    Komi_None = 2
    Email_Contact = "email"
    No_Contact = "none"

    # "I" is purposefully skipped because historically people got confused between "I" and "J".
    Column_Names = [
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",
        "P",
        "Q",
        "R",
        "S",
        "T",
    ]

    # Current on-disk schema version for GameBoard/GameState. Rows written by this
    # code are always at this version; the migration from App Engine upgrades all
    # legacy rows up to this version at import time.
    Schema_Version = 3


# ---------------------------------------------------------------------------
# Handicap helpers
# ---------------------------------------------------------------------------


def handicap_position(stone: int, handicap: int, size_index: int, version: int) -> tuple[int, int]:
    """Return the ``(x, y)`` coordinate for a single handicap stone."""
    # Placement of the centre stone was changed in version 1.
    if version >= 1 and stone >= 4 and (handicap == 6 or handicap == 8):
        # If the handicap is 6 or 8, skip the centre stone.
        return CONST.Handicap_Positions[size_index][stone + 1]
    return CONST.Handicap_Positions[size_index][stone]


def handicap_positions(handicap: int, size_index: int, version: int) -> list[tuple[int, int]]:
    """Return the list of ``(x, y)`` coordinates for every handicap stone."""
    return [handicap_position(i, handicap, size_index, version) for i in range(handicap)]


def opposite_color(color: int) -> int:
    """Return the opposite of ``Black_Color``/``White_Color``."""
    return 3 - color


def pos_to_coord(pos: tuple[int, int]) -> str:
    """Convert an ``(x, y)`` board position into SGF-style letter coordinates."""
    x, y = pos
    return f"{string.ascii_letters[x]}{string.ascii_letters[y]}"


# ---------------------------------------------------------------------------
# BoardArray: flat width*height scratch grid, used only by game logic.
# ---------------------------------------------------------------------------


class BoardArray:
    """Ephemeral scratch grid used during flood fills. Not persisted."""

    def __init__(self, width: int = 19, height: int = 19, default: int = 0) -> None:
        """Allocate a ``width * height`` grid pre-filled with ``default``."""
        self.width = width
        self.height = height
        self._cells = [default] * (width * height)

    def _index(self, x: int, y: int) -> int:
        """Return the flat index for ``(x, y)`` with bounds checks."""
        assert 0 <= x < self.width
        assert 0 <= y < self.height
        return y * self.height + x

    def get(self, x: int, y: int) -> int:
        """Return the value stored at ``(x, y)``."""
        return self._cells[self._index(x, y)]

    def set(self, x: int, y: int, value: int) -> None:
        """Store ``value`` at ``(x, y)``."""
        self._cells[self._index(x, y)] = value


# ---------------------------------------------------------------------------
# GameBoard
# ---------------------------------------------------------------------------


class GameBoard:
    """
    A Go board.

    Tracks stone positions, territory ownership (during scoring), handicap
    placement, and komi. Serializable to/from JSON via ``to_jsonable`` /
    ``from_jsonable``.
    """

    def __init__(
        self,
        board_size_index: int = 0,
        handicap_index: int = 0,
        komi_index: int = 0,
    ) -> None:
        """Create an empty board and apply the configured handicap stones."""
        self.width, self.height = CONST.Board_Sizes[board_size_index]
        self.size_index = board_size_index
        self.handicap_index = handicap_index
        self._version = CONST.Schema_Version
        self._komi_index = komi_index
        self._has_owners = False
        self.board: list[list[int]] = self._empty_grid()
        self.owners: list[list[int]] = self._empty_grid()
        self._apply_handicap()

    def _empty_grid(self) -> list[list[int]]:
        """Return a fresh ``width * height`` grid filled with ``No_Color``."""
        return [[CONST.No_Color] * self.height for _ in range(self.width)]

    def _apply_handicap(self) -> None:
        """Place the configured handicap stones on the board."""
        for x, y in self.get_handicap_positions():
            self.set(x, y, CONST.Black_Color)

    # ---- serialization ----

    def to_jsonable(self) -> dict[str, t.Any]:
        """Return a JSON-safe dict that fully captures this board."""
        return {
            "width": self.width,
            "height": self.height,
            "size_index": self.size_index,
            "handicap_index": self.handicap_index,
            "komi_index": self._komi_index,
            "version": self._version,
            "has_owners": self._has_owners,
            "board": self.board,
            "owners": self.owners if self._has_owners else None,
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, t.Any]) -> GameBoard:
        """Reconstruct a ``GameBoard`` from its ``to_jsonable`` output."""
        self = cls.__new__(cls)
        self.width = data["width"]
        self.height = data["height"]
        self.size_index = data["size_index"]
        self.handicap_index = data["handicap_index"]
        self._komi_index = data["komi_index"]
        self._version = data.get("version", CONST.Schema_Version)
        self._has_owners = bool(data.get("has_owners", False))
        self.board = [list(col) for col in data["board"]]
        if self._has_owners and data.get("owners") is not None:
            self.owners = [list(col) for col in data["owners"]]
        else:
            self.owners = self._empty_grid()
        return self

    # ---- position getters/setters ----

    def get(self, x: int, y: int) -> int:
        """Return the color of the stone at ``(x, y)`` (may be ``No_Color``)."""
        return self.board[x][y]

    def set(self, x: int, y: int, color: int) -> None:
        """Set the stone color at ``(x, y)``."""
        self.board[x][y] = color

    def get_owner(self, x: int, y: int) -> int:
        """Return the territory/dead-stone owner at ``(x, y)`` during scoring."""
        if self._has_owners:
            return self.owners[x][y]
        return CONST.No_Color

    def set_owner(self, x: int, y: int, color: int) -> None:
        """Set the territory/dead-stone owner at ``(x, y)`` during scoring."""
        if not self._has_owners:
            self.owners = self._empty_grid()
            self._has_owners = True
        self.owners[x][y] = color

    def has_owners(self) -> bool:
        """Return ``True`` if any territory/ownership data has been recorded."""
        return self._has_owners

    def get_version(self) -> int:
        """Return the on-disk schema version of this board."""
        return self._version

    # ---- metadata ----

    def get_width(self) -> int:
        """Return the board width in points."""
        return self.width

    def get_height(self) -> int:
        """Return the board height in points."""
        return self.height

    def get_size_index(self) -> int:
        """Return the board-size index into ``CONST.Board_Sizes``."""
        return self.size_index

    def get_handicap_positions(self) -> list[tuple[int, int]]:
        """Return the coordinates of all handicap stones for this board."""
        return handicap_positions(self.get_handicap(), self.size_index, self._version)

    def get_column_names(self) -> list[str]:
        """Return the A-through-T column labels for this board's width."""
        return CONST.Column_Names[: self.width]

    def get_row_names(self) -> list[str]:
        """Return the row labels for this board's height, top-down."""
        return [str(i) for i in range(self.height, 0, -1)]

    def get_komi_index(self) -> int:
        """Return the komi index into ``CONST.Komis``."""
        return self._komi_index

    def get_komi(self) -> float:
        """Return the komi value (compensation for playing White)."""
        return CONST.Komis[self._komi_index]

    def get_handicap(self) -> int:
        """Return the handicap stone count for this board."""
        return CONST.Handicaps[self.handicap_index]

    def get_class(self) -> str:
        """Return the CSS class name the frontend uses for this board size."""
        return CONST.Board_Classes[self.size_index]

    # ---- board-state string ----

    def get_state_string(self) -> str:
        """Return a compact 2D encoding of the board for the JS client."""
        parts: list[str] = []
        for y in range(self.height):
            for x in range(self.width):
                piece = self.get(x, y)
                owner = self.get_owner(x, y)
                if piece == CONST.Black_Color:
                    parts.append("c" if owner == CONST.White_Color else "b")
                elif piece == CONST.White_Color:
                    parts.append("x" if owner == CONST.Black_Color else "w")
                else:
                    if owner == CONST.Black_Color:
                        parts.append("B")
                    elif owner == CONST.White_Color:
                        parts.append("W")
                    else:
                        parts.append(".")
        return "".join(parts)

    # ---- game logic ----

    def is_in_bounds(self, x: int, y: int) -> bool:
        """Return ``True`` if ``(x, y)`` is a valid point on this board."""
        return 0 <= x < self.width and 0 <= y < self.height

    def is_stone_in_suicide(self, x: int, y: int) -> bool:
        """Return ``True`` if the stone at ``(x, y)`` has zero liberties."""
        return LibertyFinder(self, x, y).get_liberty_count() == 0

    def _compute_liberties_at(
        self, x: int, y: int, other: int
    ) -> tuple[int, list[tuple[int, int]]]:
        """Return liberty count and group for the ``other``-colored stone at ``(x, y)``.

        Returns ``(0, [])`` if the point is off-board or not the expected color.
        """
        if not self.is_in_bounds(x, y) or self.get(x, y) != other:
            return (0, [])
        finder = LibertyFinder(self, x, y)
        return (finder.get_liberty_count(), finder.get_connected_stones())

    def compute_atari_and_captures(self, x: int, y: int) -> tuple[int, list[tuple[int, int]]]:
        """
        Return ``(atari_count, captured_stones)`` after the move at ``(x, y)``.

        ``atari_count`` is the number of adjacent enemy groups reduced to one
        liberty. ``captured_stones`` is the deduplicated list of adjacent enemy
        stones now at zero liberties.
        """
        color = self.get(x, y)
        other = opposite_color(color)

        neighbors = [
            self._compute_liberties_at(x - 1, y, other),
            self._compute_liberties_at(x, y - 1, other),
            self._compute_liberties_at(x + 1, y, other),
            self._compute_liberties_at(x, y + 1, other),
        ]

        ataris = 0
        captured_groups: list[list[tuple[int, int]]] = []
        for count, connected in neighbors:
            if count == 1:
                ataris += 1
            if count == 0:
                captured_groups.append(connected)

        seen: set[tuple[int, int]] = set()
        final_captures: list[tuple[int, int]] = []
        for group in captured_groups:
            for pos in group:
                if pos not in seen:
                    seen.add(pos)
                    final_captures.append(pos)
        return (ataris, final_captures)

    def is_stone_of_color(self, x: int, y: int, color: int) -> bool:
        """Return ``True`` if ``(x, y)`` holds a stone of the requested color.

        ``Both_Colors`` matches any non-empty point.
        """
        if color == CONST.Both_Colors:
            return self.get(x, y) != CONST.No_Color
        return color == self.get(x, y)

    def is_alive(self, x: int, y: int, color: int = CONST.Both_Colors) -> bool:
        """Return ``True`` if ``(x, y)`` holds a live stone of the requested color."""
        if self.get_owner(x, y) == CONST.No_Color:
            return self.is_stone_of_color(x, y, color)
        return False

    def is_dead(self, x: int, y: int, color: int = CONST.Both_Colors) -> bool:
        """Return ``True`` if ``(x, y)`` holds a dead (marked) stone of the color."""
        if self.get_owner(x, y) == CONST.No_Color:
            return False
        return self.is_stone_of_color(x, y, color)

    def _flood(
        self,
        start_x: int,
        start_y: int,
        visit: t.Callable[[int, int, t.Callable[[int, int], None]], None],
    ) -> None:
        """
        Run a 4-connected flood fill from ``(start_x, start_y)``.

        ``visit(x, y, enqueue)`` is called for each popped cell and may call
        ``enqueue(nx, ny)`` to schedule neighbors for future visits.
        """
        visited = BoardArray(width=self.width, height=self.height)
        stack: list[tuple[int, int]] = [(start_x, start_y)]
        visited.set(start_x, start_y, 1)

        def enqueue(nx: int, ny: int) -> None:
            """Add ``(nx, ny)`` to the visit stack if in-bounds and unvisited."""
            if self.is_in_bounds(nx, ny) and visited.get(nx, ny) == 0:
                visited.set(nx, ny, 1)
                stack.append((nx, ny))

        while stack:
            x, y = stack.pop()
            visit(x, y, enqueue)

    def compute_changed_stones(self, start_x: int, start_y: int) -> list[tuple[int, int]]:
        """
        Return the stones that flip dead/alive when marking a group at ``(start_x, start_y)``.

        Used during the scoring phase when a player clicks a stone to toggle
        its dead status.
        """
        color = self.get(start_x, start_y)
        other_color = opposite_color(color)
        coords: list[tuple[int, int]] = []

        def visit(x: int, y: int, enqueue: t.Callable[[int, int], None]) -> None:
            """Record stones that belong to the marked group and expand frontier."""
            if not self.is_alive(x, y, other_color):
                if self.get(x, y) == color:
                    coords.append((x, y))
                enqueue(x + 1, y)
                enqueue(x - 1, y)
                enqueue(x, y + 1)
                enqueue(x, y - 1)

        self._flood(start_x, start_y, visit)
        return coords

    def search_for_owner(self, start_x: int, start_y: int) -> tuple[list[tuple[int, int]], int]:
        """
        Find the empty/dead region connected to ``(start_x, start_y)`` and its owner.

        Returns ``(coords_in_region, owner_color)`` where ``owner_color`` is
        one of ``No_Color`` / ``Black_Color`` / ``White_Color`` depending on
        which live colors border the region.
        """
        found_black = False
        found_white = False
        coords: list[tuple[int, int]] = []

        def visit(x: int, y: int, enqueue: t.Callable[[int, int], None]) -> None:
            """Classify neighbors as live-black / live-white or extend region."""
            nonlocal found_black, found_white
            if self.is_alive(x, y, CONST.Black_Color):
                found_black = True
            elif self.is_alive(x, y, CONST.White_Color):
                found_white = True
            else:
                coords.append((x, y))
                enqueue(x + 1, y)
                enqueue(x - 1, y)
                enqueue(x, y + 1)
                enqueue(x, y - 1)

        self._flood(start_x, start_y, visit)

        if found_black and not found_white:
            owner = CONST.Black_Color
        elif found_white and not found_black:
            owner = CONST.White_Color
        else:
            owner = CONST.No_Color
        return coords, owner

    def mark_territory(self) -> None:
        """Scan the whole board and stamp territory ownership on every empty region."""
        # Invariant: status holds colors [0..3]; "owned" regions are tagged with +4 below.
        status = BoardArray(width=self.width, height=self.height)
        found_live = False
        found_dead = False
        for x in range(self.width):
            for y in range(self.height):
                if self.is_alive(x, y):
                    status.set(x, y, self.get(x, y))
                    found_live = True
                else:
                    status.set(x, y, CONST.No_Color)
                    if not found_dead and self.is_dead(x, y):
                        found_dead = True

        if found_dead and not found_live:
            # Everything can't be dead. Resurrect all stones.
            for x in range(self.width):
                for y in range(self.height):
                    self.set_owner(x, y, CONST.No_Color)
                    status.set(x, y, self.get(x, y))

        for x in range(self.width):
            for y in range(self.height):
                if status.get(x, y) == CONST.No_Color:
                    coords, owner = self.search_for_owner(x, y)
                    for a, b in coords:
                        status.set(a, b, owner + 4)

        for x in range(self.width):
            for y in range(self.height):
                owner = status.get(x, y)
                if owner >= 4:
                    owner -= 4
                    if self.is_stone_of_color(x, y, owner):
                        self.set_owner(x, y, CONST.No_Color)
                    else:
                        self.set_owner(x, y, owner)

    def count_territory(self, color: int, captures: int = 0) -> float:
        """Return ``color``'s territory score, optionally seeded with captures."""
        count: float = captures
        opposite = opposite_color(color)
        for x in range(self.width):
            for y in range(self.height):
                if self.get_owner(x, y) == color:
                    count += 1
                    if self.get(x, y) == opposite:
                        count += 1
        return count

    def count_white_territory(self, black_stones_captured: int) -> float:
        """Return White's final score including komi and captured Black stones."""
        return self.count_territory(CONST.White_Color, black_stones_captured) + self.get_komi()

    def count_black_territory(self, white_stones_captured: int) -> float:
        """Return Black's final score including captured White stones."""
        return self.count_territory(CONST.Black_Color, white_stones_captured)

    def clone(self) -> GameBoard:
        """Return a deep copy of this board."""
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


class GameState:
    """
    Full game snapshot.

    Holds the board, capture counts, move bookkeeping, scoring state, and
    the declared winner once the game ends.
    """

    def __init__(self) -> None:
        """Create an empty game state with sensible defaults."""
        self.board: GameBoard | None = None
        self.white_stones_captured: int = 0
        self.black_stones_captured: int = 0
        self.whose_move: int = CONST.No_Color
        self.last_move_message: str = "It's your turn to move; this is the first move of the game."
        self.current_move_number: int = 0
        self.last_move: tuple[int, int] = (-1, -1)
        self.last_move_was_pass: bool = False
        # Scoring.
        self.scoring_number: int = -1
        self.white_territory: int = 0
        self.black_territory: int = 0
        self.black_done_number: int = -1
        self.white_done_number: int = -1
        self.winner: int = CONST.No_Color

    def to_jsonable(self) -> dict[str, t.Any]:
        """Return a JSON-safe dict that fully captures this game state."""
        return {
            "board": self.board.to_jsonable() if self.board is not None else None,
            "white_stones_captured": self.white_stones_captured,
            "black_stones_captured": self.black_stones_captured,
            "whose_move": self.whose_move,
            "last_move_message": self.last_move_message,
            "current_move_number": self.current_move_number,
            "last_move": list(self.last_move),
            "last_move_was_pass": self.last_move_was_pass,
            "scoring_number": self.get_scoring_number(),
            "white_territory": self.get_white_territory(),
            "black_territory": self.get_black_territory(),
            "black_done_number": self.black_done_number,
            "white_done_number": self.white_done_number,
            "winner": self.winner,
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, t.Any]) -> GameState:
        """Reconstruct a ``GameState`` from its ``to_jsonable`` output."""
        self = cls()
        board_data = data.get("board")
        self.board = GameBoard.from_jsonable(board_data) if board_data is not None else None
        self.white_stones_captured = int(data["white_stones_captured"])
        self.black_stones_captured = int(data["black_stones_captured"])
        self.whose_move = int(data["whose_move"])
        self.last_move_message = data["last_move_message"]
        self.current_move_number = int(data["current_move_number"])
        last_move = data["last_move"]
        self.last_move = (int(last_move[0]), int(last_move[1]))
        self.last_move_was_pass = bool(data["last_move_was_pass"])
        self.scoring_number = int(data.get("scoring_number", -1))
        self.white_territory = int(data.get("white_territory", 0))
        self.black_territory = int(data.get("black_territory", 0))
        self.black_done_number = int(data.get("black_done_number", -1))
        self.white_done_number = int(data.get("white_done_number", -1))
        self.winner = int(data.get("winner", CONST.No_Color))
        return self

    # ---- board access ----

    def get_board(self) -> GameBoard:
        """Return the current ``GameBoard``. Must have been set previously."""
        assert self.board is not None
        return self.board

    def set_board(self, board: GameBoard) -> None:
        """Set the current ``GameBoard``."""
        self.board = board

    def get_version(self) -> int:
        """Return the on-disk schema version of the underlying board."""
        return self.get_board().get_version()

    # ---- turn bookkeeping ----

    def get_whose_move(self) -> int:
        """Return the color whose turn it is to move."""
        return self.whose_move

    def set_whose_move(self, whose_move: int) -> None:
        """Set the color whose turn it is to move."""
        self.whose_move = whose_move

    def get_white_stones_captured(self) -> int:
        """Return the number of White stones that have been captured."""
        return self.white_stones_captured

    def set_white_stones_captured(self, v: int) -> None:
        """Set the number of White stones that have been captured."""
        self.white_stones_captured = v

    def get_black_stones_captured(self) -> int:
        """Return the number of Black stones that have been captured."""
        return self.black_stones_captured

    def set_black_stones_captured(self, v: int) -> None:
        """Set the number of Black stones that have been captured."""
        self.black_stones_captured = v

    # ---- scoring ----

    def get_scoring_number(self) -> int:
        """Return the current scoring round number (-1 before scoring starts)."""
        return self.scoring_number

    def increment_scoring_number(self) -> None:
        """Advance to the next scoring round."""
        self.scoring_number += 1

    def has_scoring_data(self) -> bool:
        """Return ``True`` if the game has entered scoring."""
        return self.get_scoring_number() >= 0

    def is_white_done_scoring(self) -> bool:
        """Return ``True`` if White has confirmed the current scoring round."""
        return self.has_scoring_data() and self.white_done_number == self.get_scoring_number()

    def is_black_done_scoring(self) -> bool:
        """Return ``True`` if Black has confirmed the current scoring round."""
        return self.has_scoring_data() and self.black_done_number == self.get_scoring_number()

    def is_done_scoring(self, color: int = CONST.Both_Colors) -> bool:
        """Return ``True`` if the given color (or both) has finished scoring."""
        if color == CONST.White_Color:
            return self.is_white_done_scoring()
        if color == CONST.Black_Color:
            return self.is_black_done_scoring()
        return self.is_white_done_scoring() and self.is_black_done_scoring()

    def set_done_scoring(self, color: int) -> None:
        """Mark the given color as done for the current scoring round."""
        if color == CONST.White_Color:
            self.white_done_number = self.get_scoring_number()
        elif color == CONST.Black_Color:
            self.black_done_number = self.get_scoring_number()

    def get_winner(self) -> int:
        """Return the declared winning color (``No_Color`` if undecided)."""
        return self.winner

    def is_winner(self, color: int) -> bool:
        """Return ``True`` if the given color is the declared winner."""
        return color == self.winner

    def set_winner(self, color: int) -> None:
        """Declare the winning color."""
        self.winner = color

    def get_white_territory(self) -> int:
        """Return White's territory count (or -1 before scoring starts)."""
        return self.white_territory if self.has_scoring_data() else -1

    def set_white_territory(self, t_: int) -> None:
        """Set White's territory count."""
        self.white_territory = t_

    def get_black_territory(self) -> int:
        """Return Black's territory count (or -1 before scoring starts)."""
        return self.black_territory if self.has_scoring_data() else -1

    def set_black_territory(self, t_: int) -> None:
        """Set Black's territory count."""
        self.black_territory = t_

    def count_territory(self) -> None:
        """Recompute and store both players' territory counts from the board."""
        board = self.get_board()
        self.set_black_territory(int(board.count_black_territory(self.get_white_stones_captured())))
        self.set_white_territory(int(board.count_white_territory(self.get_black_stones_captured())))

    # ---- move bookkeeping ----

    def get_last_move_message(self) -> str:
        """Return the human-readable message describing the last move."""
        return self.last_move_message

    def set_last_move_message(self, message: str) -> None:
        """Set the human-readable message describing the last move."""
        self.last_move_message = message

    def get_current_move_number(self) -> int:
        """Return the current 0-based move number."""
        return self.current_move_number

    def set_current_move_number(self, number: int) -> None:
        """Set the current 0-based move number."""
        self.current_move_number = number

    def increment_current_move_number(self, by: int = 1) -> None:
        """Advance the current move number by ``by``."""
        self.current_move_number += by

    def get_last_move(self) -> tuple[int, int]:
        """Return the ``(x, y)`` coordinates of the last move (or ``(-1, -1)``)."""
        return self.last_move

    def set_last_move(self, x: int, y: int) -> None:
        """Set the ``(x, y)`` coordinates of the last move."""
        self.last_move = (x, y)

    def get_last_move_was_pass(self) -> bool:
        """Return ``True`` if the last move was a pass."""
        return self.last_move_was_pass

    def set_last_move_was_pass(self, was_pass: bool) -> None:
        """Set whether the last move was a pass."""
        self.last_move_was_pass = was_pass

    def clone(self) -> GameState:
        """Return a deep copy of this game state."""
        c = GameState()
        c.white_stones_captured = self.white_stones_captured
        c.black_stones_captured = self.black_stones_captured
        c.whose_move = self.whose_move
        c.last_move_message = self.last_move_message
        c.current_move_number = self.current_move_number
        c.board = self.get_board().clone()
        c.last_move = self.last_move
        c.last_move_was_pass = self.last_move_was_pass
        if self.has_scoring_data():
            c.scoring_number = self.scoring_number
            c.white_territory = self.white_territory
            c.black_territory = self.black_territory
            c.black_done_number = self.black_done_number
            c.white_done_number = self.white_done_number
            c.winner = self.winner
        return c


# ---------------------------------------------------------------------------
# ChatEntry
# ---------------------------------------------------------------------------


class ChatEntry:
    """A single chat message tied to a player and move number."""

    def __init__(self, cookie: str, message: str, current_move_number: int) -> None:
        """Create a chat entry for the given player cookie, message, and move."""
        self.cookie = cookie
        self.message = message
        self.move_number = current_move_number

    def to_jsonable(self) -> dict[str, t.Any]:
        """Return a JSON-safe dict that fully captures this chat entry."""
        return {
            "cookie": self.cookie,
            "message": self.message,
            "move_number": self.move_number,
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, t.Any]) -> ChatEntry:
        """Reconstruct a ``ChatEntry`` from its ``to_jsonable`` output."""
        return cls(data["cookie"], data["message"], int(data["move_number"]))

    def get_cookie(self) -> str:
        """Return the cookie of the player who sent this message."""
        return self.cookie

    def get_message(self) -> str:
        """Return the chat message body."""
        return self.message

    def get_move_number(self) -> int:
        """Return the move number this chat was attached to."""
        return self.move_number


# ---------------------------------------------------------------------------
# LibertyFinder: connected-component + liberty counter for a stone group
# ---------------------------------------------------------------------------


class LibertyFinder:
    """Finds the connected group and counts liberties of a stone at ``(start_x, start_y)``."""

    def __init__(self, board: GameBoard, start_x: int, start_y: int) -> None:
        """Run the flood fill and liberty count immediately."""
        self.board = board
        self.start_x = start_x
        self.start_y = start_y
        self.color = board.get(start_x, start_y)
        self.connected_stones: list[tuple[int, int]] = []
        self.liberty_count: int = 0
        self._find_connected_stones()
        self._count_liberties()

    def _find_connected_stones(self) -> None:
        """Populate ``self.connected_stones`` via BFS on same-color neighbors."""
        w = self.board.get_width()
        h = self.board.get_height()
        reached = [[False] * h for _ in range(w)]
        q: deque[tuple[int, int]] = deque()
        q.append((self.start_x, self.start_y))

        while q:
            x, y = q.popleft()
            if reached[x][y]:
                continue
            reached[x][y] = True
            self.connected_stones.append((x, y))

            for nx, ny in ((x - 1, y), (x, y - 1), (x + 1, y), (x, y + 1)):
                if (
                    0 <= nx < w
                    and 0 <= ny < h
                    and not reached[nx][ny]
                    and self.board.get(nx, ny) == self.color
                ):
                    q.append((nx, ny))

        # Canonical order so two groups can be equality-compared.
        self.connected_stones.sort()

    def _count_liberties(self) -> None:
        """Populate ``self.liberty_count`` by scanning empty neighbors once each."""
        w = self.board.get_width()
        h = self.board.get_height()
        already_counted = [[False] * h for _ in range(w)]
        self.liberty_count = 0
        for x, y in self.connected_stones:
            for nx, ny in ((x - 1, y), (x, y - 1), (x + 1, y), (x, y + 1)):
                if (
                    0 <= nx < w
                    and 0 <= ny < h
                    and self.board.get(nx, ny) == CONST.No_Color
                    and not already_counted[nx][ny]
                ):
                    already_counted[nx][ny] = True
                    self.liberty_count += 1

    def get_liberty_count(self) -> int:
        """Return the number of liberties of the group."""
        return self.liberty_count

    def get_connected_stones(self) -> list[tuple[int, int]]:
        """Return the sorted list of stones in the group."""
        return self.connected_stones


# ---------------------------------------------------------------------------
# GameCookie: random base-62 identifier for a player-in-game
# ---------------------------------------------------------------------------


_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class GameCookie:
    """Random base-62 cookie generation for identifying a player in a game."""

    @staticmethod
    def _base_n(num: int, base: int) -> str:
        """Encode ``num`` in the given ``base`` using ``_BASE62`` digits."""
        if num == 0:
            return "0"
        digits: list[str] = []
        while num > 0:
            digits.append(_BASE62[num % base])
            num //= base
        return "".join(reversed(digits))

    @staticmethod
    def _base_62(num: int) -> str:
        """Encode ``num`` in base 62 (short URL-safe strings)."""
        return GameCookie._base_n(num, 62)

    @staticmethod
    def random_cookie() -> str:
        """Return a random base-62 cookie (not guaranteed unique in the DB)."""
        return GameCookie._base_62(random.randint(1, 50_000_000_000))

    @staticmethod
    def unique_pair(exists_func: t.Callable[[str], bool]) -> tuple[str, str]:
        """
        Return two guaranteed-unique (and non-identical) cookies.

        ``exists_func(cookie) -> bool`` is the DB uniqueness probe; pulled out
        as an injected callable so game_logic has no Django dependency.
        """
        while True:
            one = GameCookie.random_cookie()
            two = GameCookie.random_cookie()
            while one == two:
                two = GameCookie.random_cookie()
            if not exists_func(one) and not exists_func(two):
                return (one, two)
