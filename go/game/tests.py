"""
Tests for game_logic and the Django model bridge.

These cover the high-risk pieces of the port:
- JSON round-trip for ``GameBoard`` / ``GameState`` / ``ChatEntry``
- ``LibertyFinder`` liberty counting
- ``compute_atari_and_captures`` basic capture
- ``mark_territory`` identifies clear territory
- ``Game.load_state`` / ``save_state`` round-trips through the ORM
- ``Player.by_cookie`` lookup
"""

from datetime import UTC, datetime

from django.test import TestCase

from .game_logic import (
    CONST,
    BoardArray,
    ChatEntry,
    GameBoard,
    GameCookie,
    GameState,
    LibertyFinder,
    opposite_color,
    pos_to_coord,
)
from .models import Game, Player


class BoardArrayTests(TestCase):
    """Ephemeral scratch grid behavior."""

    def test_default_zero(self) -> None:
        """A fresh ``BoardArray`` returns 0 everywhere."""
        ba = BoardArray(width=5, height=5)
        self.assertEqual(ba.get(0, 0), 0)
        self.assertEqual(ba.get(4, 4), 0)

    def test_set_get(self) -> None:
        """``set`` and ``get`` round-trip a single cell."""
        ba = BoardArray(width=5, height=5)
        ba.set(2, 3, 7)
        self.assertEqual(ba.get(2, 3), 7)


class GameBoardJsonTests(TestCase):
    """GameBoard serialization round-trip and owner semantics."""

    def test_round_trip_plain(self) -> None:
        """A 19x19 board with a few stones round-trips exactly."""
        b = GameBoard(board_size_index=0, handicap_index=0, komi_index=0)
        b.set(0, 0, CONST.Black_Color)
        b.set(1, 0, CONST.White_Color)
        data = b.to_jsonable()
        b2 = GameBoard.from_jsonable(data)
        self.assertEqual(b2.to_jsonable(), data)
        self.assertEqual(b2.get(0, 0), CONST.Black_Color)
        self.assertEqual(b2.get(1, 0), CONST.White_Color)

    def test_round_trip_with_owners(self) -> None:
        """Owner grid is emitted and restored when ``set_owner`` is called."""
        b = GameBoard(board_size_index=2)  # 9x9
        b.set(4, 4, CONST.Black_Color)
        b.set_owner(3, 3, CONST.White_Color)
        data = b.to_jsonable()
        self.assertTrue(data["has_owners"])
        b2 = GameBoard.from_jsonable(data)
        self.assertEqual(b2.get_owner(3, 3), CONST.White_Color)

    def test_handicap_9x9_two_stones(self) -> None:
        """Handicap index 8 (== 2 stones) is applied at creation."""
        b = GameBoard(board_size_index=2, handicap_index=8)
        self.assertEqual(b.get(6, 2), CONST.Black_Color)
        self.assertEqual(b.get(2, 6), CONST.Black_Color)


class GameStateJsonTests(TestCase):
    """GameState serialization round-trip, including scoring fields."""

    def test_round_trip(self) -> None:
        """Fresh state round-trips exactly."""
        s = GameState()
        s.set_board(GameBoard(board_size_index=0))
        s.whose_move = CONST.White_Color
        s.set_last_move(3, 4)
        self.assertEqual(GameState.from_jsonable(s.to_jsonable()).to_jsonable(), s.to_jsonable())

    def test_scoring_round_trip(self) -> None:
        """Scoring fields round-trip when set."""
        s = GameState()
        s.set_board(GameBoard(board_size_index=0))
        s.scoring_number = 0
        s.white_territory = 20
        s.black_territory = 30
        s.winner = CONST.White_Color
        out = GameState.from_jsonable(s.to_jsonable())
        self.assertTrue(out.has_scoring_data())
        self.assertEqual(out.get_white_territory(), 20)
        self.assertEqual(out.get_winner(), CONST.White_Color)


class ChatEntryJsonTests(TestCase):
    """ChatEntry serialization round-trip."""

    def test_round_trip(self) -> None:
        """Cookie, message, and move_number round-trip."""
        c = ChatEntry("abc", "Hi there!", 7)
        out = ChatEntry.from_jsonable(c.to_jsonable())
        self.assertEqual(out.get_cookie(), "abc")
        self.assertEqual(out.get_message(), "Hi there!")
        self.assertEqual(out.get_move_number(), 7)


class LibertyFinderTests(TestCase):
    """Liberty counting for single stones and groups."""

    def test_lone_stone_center(self) -> None:
        """A stone in the center of a 9x9 has 4 liberties."""
        b = GameBoard(board_size_index=2)
        b.set(4, 4, CONST.Black_Color)
        lf = LibertyFinder(b, 4, 4)
        self.assertEqual(lf.get_liberty_count(), 4)
        self.assertEqual(lf.get_connected_stones(), [(4, 4)])

    def test_corner_stone(self) -> None:
        """A stone in the corner of a 9x9 has 2 liberties."""
        b = GameBoard(board_size_index=2)
        b.set(0, 0, CONST.Black_Color)
        self.assertEqual(LibertyFinder(b, 0, 0).get_liberty_count(), 2)

    def test_connected_two_stones(self) -> None:
        """Two adjacent edge stones share 3 liberties."""
        b = GameBoard(board_size_index=2)
        b.set(0, 0, CONST.Black_Color)
        b.set(1, 0, CONST.Black_Color)
        lf = LibertyFinder(b, 0, 0)
        self.assertEqual(lf.get_liberty_count(), 3)
        self.assertEqual(sorted(lf.get_connected_stones()), [(0, 0), (1, 0)])


class CaptureTests(TestCase):
    """``compute_atari_and_captures`` basic scenarios."""

    def test_simple_capture(self) -> None:
        """Surrounding a lone White stone on all four sides captures it."""
        b = GameBoard(board_size_index=2)
        # White in the middle, surrounded on three sides.
        b.set(4, 4, CONST.White_Color)
        b.set(3, 4, CONST.Black_Color)
        b.set(5, 4, CONST.Black_Color)
        b.set(4, 3, CONST.Black_Color)
        # Black plays the fourth.
        b.set(4, 5, CONST.Black_Color)
        ataris, captures = b.compute_atari_and_captures(4, 5)
        self.assertEqual(ataris, 0)
        self.assertIn((4, 4), captures)


class TerritoryTests(TestCase):
    """``mark_territory`` identifies simple Black territory."""

    def test_enclosed_territory(self) -> None:
        """A small enclosed empty region is assigned to the enclosing color."""
        b = GameBoard(board_size_index=2)  # 9x9
        # Build a small Black enclosure around (1,1).
        for x in range(3):
            b.set(x, 0, CONST.Black_Color)
            b.set(x, 2, CONST.Black_Color)
        b.set(0, 1, CONST.Black_Color)
        b.set(2, 1, CONST.Black_Color)
        # Everything else is empty; the "outside" is also empty so the outside
        # gets No_Color. The enclosed cell (1, 1) should be Black-owned.
        b.mark_territory()
        self.assertEqual(b.get_owner(1, 1), CONST.Black_Color)


class MiscUtilTests(TestCase):
    """Tiny helpers: opposite_color, pos_to_coord, GameCookie."""

    def test_opposite_color(self) -> None:
        """Black and White swap; No_Color is the identity."""
        self.assertEqual(opposite_color(CONST.Black_Color), CONST.White_Color)
        self.assertEqual(opposite_color(CONST.White_Color), CONST.Black_Color)

    def test_pos_to_coord(self) -> None:
        """Position maps to two letters of the same case sequence."""
        self.assertEqual(pos_to_coord((0, 0)), "aa")
        self.assertEqual(pos_to_coord((1, 2)), "bc")

    def test_game_cookie_unique_pair_accepts_new(self) -> None:
        """``unique_pair`` returns two distinct non-empty cookies."""
        one, two = GameCookie.unique_pair(lambda _: False)
        self.assertNotEqual(one, two)
        self.assertGreater(len(one), 0)
        self.assertGreater(len(two), 0)


class GameBridgeTests(TestCase):
    """Game model's state helpers round-trip through the ORM."""

    def _base_game(self) -> Game:
        """Create and return a saved minimal Game row for use in tests."""
        b = GameBoard(board_size_index=0)
        s = GameState()
        s.set_board(b)
        s.whose_move = CONST.Black_Color
        now = datetime.now(UTC)
        return Game.objects.create(
            date_created=now,
            date_last_moved=now,
            current_state=s.to_jsonable(),
            history=[],
            chat_history=[],
            black_cookie="bbb",
            white_cookie="www",
        )

    def test_load_save_state(self) -> None:
        """``save_state`` then ``load_state`` preserves whose-move and a stone."""
        game = self._base_game()
        state = game.load_state()
        state.whose_move = CONST.White_Color
        state.get_board().set(2, 2, CONST.Black_Color)
        game.save_state(state)
        game.save()

        refetched = Game.objects.get(pk=game.pk)
        reloaded = refetched.load_state()
        self.assertEqual(reloaded.whose_move, CONST.White_Color)
        self.assertEqual(reloaded.get_board().get(2, 2), CONST.Black_Color)

    def test_append_history_and_chat(self) -> None:
        """``append_history`` and ``append_chat`` grow their JSON lists."""
        game = self._base_game()
        state = game.load_state()
        game.append_history(state)
        game.append_chat(ChatEntry("bbb", "hi", 0))
        game.save()

        refetched = Game.objects.get(pk=game.pk)
        self.assertEqual(len(refetched.history), 1)
        self.assertEqual(len(refetched.chat_history), 1)
        self.assertEqual(refetched.load_chat()[0].get_message(), "hi")


class PlayerBridgeTests(TestCase):
    """Player.by_cookie and friendly-name helpers."""

    def test_by_cookie_round_trip(self) -> None:
        """A saved player can be looked up by its cookie."""
        now = datetime.now(UTC)
        game = Game.objects.create(
            date_created=now,
            date_last_moved=now,
            current_state={},
            history=[],
            chat_history=[],
            black_cookie="bbb",
            white_cookie="www",
        )
        Player.objects.create(
            game=game, cookie="bbb", color=CONST.Black_Color, name="Alice", email="a@x.com"
        )
        Player.objects.create(
            game=game, cookie="www", color=CONST.White_Color, name="Bob", email="b@x.com"
        )
        alice = Player.by_cookie("bbb")
        self.assertIsNotNone(alice)
        assert alice is not None  # narrow for ty
        self.assertEqual(alice.get_friendly_name(), "Alice")
        self.assertIsNone(Player.by_cookie("zzz"))

    def test_friendly_name_strips_email_and_truncates(self) -> None:
        """Long names are truncated; email-style names strip the domain."""
        now = datetime.now(UTC)
        game = Game.objects.create(
            date_created=now,
            date_last_moved=now,
            current_state={},
            black_cookie="a",
            white_cookie="b",
        )
        p1 = Player.objects.create(
            game=game, cookie="p1", color=CONST.Black_Color, name="dave@example.com"
        )
        p2 = Player.objects.create(game=game, cookie="p2", color=CONST.White_Color, name="x" * 40)
        self.assertEqual(p1.get_friendly_name(), "dave")
        self.assertTrue(p2.get_friendly_name().endswith("..."))
        self.assertEqual(len(p2.get_friendly_name()), 18)
