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

import typing as t
from datetime import UTC, datetime
from email.utils import parseaddr

from django.core import mail
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend
from django.test import TestCase, override_settings

from .email import _rfc_address
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


class ViewRenderTests(TestCase):
    """
    Smoke-test every player-facing GET view renders 200 on real data.

    Catches regressions in deprecated template tags (``ifequal`` et al.),
    missing context variables, and broken ``{% url %}`` / ``{% static %}``
    references. Does not exercise gameplay — see the other view test classes
    for that.
    """

    def setUp(self) -> None:
        """Create a minimal two-player game for the tests to render."""
        b = GameBoard(board_size_index=0, handicap_index=1, komi_index=2)  # 19x19, 9-stone
        s = GameState()
        s.set_board(b)
        s.whose_move = CONST.White_Color
        now = datetime.now(UTC)
        self.game = Game.objects.create(
            date_created=now,
            date_last_moved=now,
            reminder_send_time=now,
            current_state=s.to_jsonable(),
            history=[],
            chat_history=[],
            black_cookie="bcook",
            white_cookie="wcook",
        )
        Player.objects.create(
            game=self.game, cookie="bcook", color=CONST.Black_Color, name="Alice", email="a@x.com"
        )
        Player.objects.create(
            game=self.game, cookie="wcook", color=CONST.White_Color, name="Bob", email="b@x.com"
        )

    def test_splash(self) -> None:
        """The splash page renders."""
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_get_going(self) -> None:
        """The game-creation form renders."""
        self.assertEqual(self.client.get("/get-going/").status_code, 200)

    def test_play(self) -> None:
        """The live game board renders and embeds the init_play JS call."""
        r = self.client.get("/play/bcook/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"init_play(", r.content)

    def test_history(self) -> None:
        """The history browser renders."""
        self.assertEqual(self.client.get("/history/bcook/").status_code, 200)

    def test_options(self) -> None:
        """The options form renders (exercises the ``{% if ==%}`` replacements)."""
        r = self.client.get("/options/bcook/")
        self.assertEqual(r.status_code, 200)
        # Confirms the rewritten ``{% if %}`` branches still pick the right
        # copy for the player's contact_type.
        self.assertIn(b"notify me via email", r.content)

    def test_sgf_with_handicap(self) -> None:
        """SGF download emits the ``{% if handicap != 0 %}`` branch correctly."""
        r = self.client.get("/history/bcook.sgf")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("HA[9]", body)
        self.assertIn("PL[W]", body)  # handicap sets next-to-move White

    def test_sgf_without_handicap(self) -> None:
        """SGF download emits the ``{% else %}`` branch when handicap is zero."""
        b = GameBoard(board_size_index=0, handicap_index=0, komi_index=0)
        s = GameState()
        s.set_board(b)
        s.whose_move = CONST.Black_Color
        now = datetime.now(UTC)
        g2 = Game.objects.create(
            date_created=now,
            date_last_moved=now,
            current_state=s.to_jsonable(),
            history=[],
            chat_history=[],
            black_cookie="b2",
            white_cookie="w2",
        )
        Player.objects.create(
            game=g2, cookie="b2", color=CONST.Black_Color, name="A", email="a@y.com"
        )
        Player.objects.create(
            game=g2, cookie="w2", color=CONST.White_Color, name="B", email="b@y.com"
        )
        r = self.client.get("/history/b2.sgf")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn("HA[", body)
        self.assertIn("PL[B]", body)


class MaintenanceModeTests(TestCase):
    """Verify ``MaintenanceModeMiddleware`` short-circuits every request when on."""

    @override_settings(MAINTENANCE_MODE=True)
    def test_routed_url_returns_503(self) -> None:
        """A normally-200 URL returns 503 with the maintenance copy."""
        r = self.client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"right back", r.content)

    @override_settings(MAINTENANCE_MODE=True)
    def test_unrouted_url_also_returns_503(self) -> None:
        """The middleware fires before URL resolution, so even unknown paths are caught."""
        r = self.client.get("/this/path/does/not/exist/")
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"right back", r.content)


class GameplayFlowTests(TestCase):
    """
    End-to-end gameplay golden path.

    Exercises the full service-view chain go.js calls in normal play:
    create-game, make-this-move, has-opponent-moved, add-chat / recent-chat,
    pass, mark-stone, done. Uses the Django test client so CSRF-exempt
    dispatch, URL routing, JSON shape, and JSONField persistence are all
    covered in one pass.
    """

    def _json(self, path: str, **data: str | int) -> dict[str, t.Any]:
        """POST ``data`` to ``path`` and return the parsed JSON body."""
        r = self.client.post(path, data=data)
        self.assertEqual(r.status_code, 200, f"{path} -> {r.status_code}: {r.content!r}")
        return r.json()

    def _create_game(self) -> tuple[str, str]:
        """Create a 9x9 no-handicap email/email game; return (your, opp) cookies."""
        payload = self._json(
            "/service/create-game/",
            your_name="Alice",
            your_contact="alice@example.com",
            your_contact_type="email",
            opponent_name="Bob",
            opponent_contact="bob@example.com",
            opponent_contact_type="email",
            your_color=str(CONST.Black_Color),
            board_size_index="2",  # 9x9
            handicap_index="0",
            komi_index="0",
        )
        self.assertTrue(payload["success"], payload)
        self.assertTrue(payload["your_turn"])  # no handicap => Black moves first

        your_cookie = payload["your_cookie"]
        your = Player.by_cookie(your_cookie)
        assert your is not None
        opp = your.get_opponent()
        assert opp is not None
        return your_cookie, opp.cookie

    def test_full_game_golden_path(self) -> None:
        """Create a game, play a move, poll, chat, pass-pass to enter scoring."""
        alice_cookie, bob_cookie = self._create_game()

        # 1. Alice (Black) plays (4, 4) on the 9x9.
        played = self._json(
            "/service/make-this-move/",
            your_cookie=alice_cookie,
            current_move_number="0",
            move_x="4",
            move_y="4",
        )
        self.assertTrue(played["success"])
        self.assertEqual(played["current_move_number"], 1)
        self.assertEqual(played["last_move_x"], 4)
        self.assertEqual(played["last_move_y"], 4)

        # 2. Bob polls and sees the move.
        polled = self._json(
            "/service/has-opponent-moved/",
            your_cookie=bob_cookie,
        )
        self.assertTrue(polled["has_opponent_moved"])
        self.assertEqual(polled["current_move_number"], 1)
        self.assertEqual(polled["last_move_x"], 4)
        self.assertEqual(polled["last_move_y"], 4)

        # 3. Chat round-trips.
        self.assertEqual(
            self._json(
                "/service/recent-chat/",
                your_cookie=alice_cookie,
                last_chat_seen="0",
            )["chat_count"],
            0,
        )
        added = self._json(
            "/service/add-chat/",
            your_cookie=bob_cookie,
            message="Nice opening.",
            last_chat_seen="0",
        )
        self.assertEqual(added["chat_count"], 1)
        self.assertEqual(added["recent_chats"][0]["message"], "Nice opening.")

        # 4. Bob passes; Alice passes; game enters scoring.
        after_bob_pass = self._json(
            "/service/pass/",
            your_cookie=bob_cookie,
            current_move_number="1",
        )
        self.assertFalse(after_bob_pass["game_is_scoring"])
        after_alice_pass = self._json(
            "/service/pass/",
            your_cookie=alice_cookie,
            current_move_number="2",
        )
        self.assertTrue(after_alice_pass["game_is_scoring"])

        # 5. Either player marks Done; since both pass on an almost-empty board
        #    the territory scores aren't meaningful, but the flow should finish.
        alice_done = self._json(
            "/service/done/",
            your_cookie=alice_cookie,
            scoring_number=str(after_alice_pass["scoring_number"]),
        )
        self.assertTrue(alice_done["success"])
        self.assertTrue(alice_done["you_are_done_scoring"])
        bob_done = self._json(
            "/service/done/",
            your_cookie=bob_cookie,
            scoring_number=str(after_alice_pass["scoring_number"]),
        )
        self.assertTrue(bob_done["success"])
        self.assertTrue(bob_done["game_is_finished"])

    def test_create_game_rejects_invalid_email(self) -> None:
        """``/service/create-game/`` returns success=False on a bogus email."""
        r = self.client.post(
            "/service/create-game/",
            data={
                "your_name": "Alice",
                "your_contact": "not-an-email",
                "your_contact_type": "email",
                "opponent_name": "Bob",
                "opponent_contact": "bob@example.com",
                "opponent_contact_type": "email",
                "your_color": str(CONST.Black_Color),
                "board_size_index": "2",
                "handicap_index": "0",
                "komi_index": "0",
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIn("contact information is invalid", body["flash"])

    def test_make_move_wrong_turn_rejected(self) -> None:
        """The player whose turn it is *not* cannot move."""
        _, bob_cookie = self._create_game()
        r = self.client.post(
            "/service/make-this-move/",
            data={
                "your_cookie": bob_cookie,
                "current_move_number": "0",
                "move_x": "4",
                "move_y": "4",
            },
        )
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIn("not your turn", body["flash"])

    def test_resign_ends_game(self) -> None:
        """A resign finishes the game and awards the opponent the win."""
        alice_cookie, bob_cookie = self._create_game()
        payload = self._json(
            "/service/resign/",
            your_cookie=alice_cookie,
            current_move_number="0",
        )
        self.assertTrue(payload["success"])
        self.assertTrue(payload["game_is_finished"])

        # Check from Bob's side: he wins.
        bob = Player.by_cookie(bob_cookie)
        assert bob is not None
        self.assertTrue(bob.game.is_finished)
        winner_color = bob.game.load_state().get_winner()
        self.assertEqual(winner_color, CONST.White_Color)

    def test_capture_removes_stone_and_increments_counter(self) -> None:
        """
        A full capture scenario through the HTTP layer.

        Black plays at (4,4); White surrounds it by playing at the four
        cardinal neighbors over the course of alternating turns (with Black
        playing filler moves far away in between). The final White move
        captures the Black stone: the board cell becomes empty and
        ``black_stones_captured`` increments to 1.
        """
        black_cookie, white_cookie = self._create_game()

        def play(cookie: str, move_num: int, x: int, y: int) -> dict[str, t.Any]:
            """Submit ``(x, y)`` as ``cookie``'s next move."""
            return self._json(
                "/service/make-this-move/",
                your_cookie=cookie,
                current_move_number=str(move_num),
                move_x=str(x),
                move_y=str(y),
            )

        # Alternating moves. Black plays filler far from (4,4) so its stones
        # don't interfere with White's encirclement.
        play(black_cookie, 0, 4, 4)  # Black: target stone.
        play(white_cookie, 1, 3, 4)  # White: W edge.
        play(black_cookie, 2, 7, 7)  # Black filler.
        play(white_cookie, 3, 5, 4)  # White: E edge.
        play(black_cookie, 4, 7, 8)  # Black filler.
        play(white_cookie, 5, 4, 3)  # White: N edge — Black now in atari.
        play(black_cookie, 6, 7, 6)  # Black filler.
        captured = play(white_cookie, 7, 4, 5)  # White: S edge — captures.

        # The JSON response should show the capture.
        self.assertEqual(captured["black_stones_captured"], 1)
        self.assertEqual(captured["white_stones_captured"], 0)
        # The captured stone's cell should be empty in the board-state string.
        # Cells are emitted in row-major order (y outer, x inner) on a 9x9.
        board_str: str = captured["board_state_string"]
        idx = 4 * 9 + 4  # (x=4, y=4) -> y*width + x
        self.assertEqual(
            board_str[idx],
            ".",
            f"Expected empty at (4,4); got {board_str[idx]!r} in {board_str!r}",
        )

        # And the stored state should agree.
        black = Player.by_cookie(black_cookie)
        assert black is not None
        state = black.game.load_state()
        self.assertEqual(state.get_board().get(4, 4), CONST.No_Color)
        self.assertEqual(state.get_black_stones_captured(), 1)

    def test_change_options_email_to_none_and_back(self) -> None:
        """
        The options flow switches ``contact_type`` between email and none.

        Exercises the post-Twitter-purge simplification of ``ChangeOptionsView``
        and the corresponding template/JS path.
        """
        alice_cookie, _ = self._create_game()
        alice = Player.by_cookie(alice_cookie)
        assert alice is not None
        self.assertEqual(alice.contact_type, CONST.Email_Contact)
        self.assertTrue(alice.wants_email)

        # Opt out of all notifications.
        off = self._json(
            "/service/change-options/",
            your_cookie=alice_cookie,
            new_contact_type=CONST.No_Contact,
        )
        self.assertTrue(off["success"])
        alice.refresh_from_db()
        self.assertEqual(alice.contact_type, CONST.No_Contact)
        self.assertFalse(alice.wants_email)

        # Turn email back on.
        on = self._json(
            "/service/change-options/",
            your_cookie=alice_cookie,
            new_contact_type=CONST.Email_Contact,
            new_contact="alice-new@example.com",
        )
        self.assertTrue(on["success"])
        alice.refresh_from_db()
        self.assertEqual(alice.contact_type, CONST.Email_Contact)
        self.assertTrue(alice.wants_email)
        self.assertEqual(alice.email, "alice-new@example.com")

    def test_change_options_rejects_bad_email(self) -> None:
        """A malformed email address fails validation and leaves state intact."""
        alice_cookie, _ = self._create_game()
        r = self.client.post(
            "/service/change-options/",
            data={
                "your_cookie": alice_cookie,
                "new_contact_type": CONST.Email_Contact,
                "new_contact": "not-an-email",
            },
        )
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIn("Invalid email", body["flash"])

    def test_historical_state_views(self) -> None:
        """
        Both historical-state endpoints return the right earlier state.

        Plays one move, then reads back the pre-move state via both
        ``/history/<cookie>/0/`` (HTML) and ``/service/get-historical-state/``
        (JSON) — these are the paths the history browser uses.
        """
        black_cookie, _ = self._create_game()
        self._json(
            "/service/make-this-move/",
            your_cookie=black_cookie,
            current_move_number="0",
            move_x="4",
            move_y="4",
        )

        # HTML render at move 0: an empty 9x9 board is passed to init_history.
        html = self.client.get(f"/history/{black_cookie}/0/")
        self.assertEqual(html.status_code, 200)
        self.assertIn(b"init_history(", html.content)
        # The 9x9 board is encoded as 81 dots (no stones at move 0).
        self.assertIn(b"." * 81, html.content)

        # JSON snapshot at move 0.
        snap = self._json(
            "/service/get-historical-state/",
            your_cookie=black_cookie,
            move_number="0",
        )
        self.assertEqual(snap["current_move_number"], 0)
        self.assertEqual(snap["last_move_x"], -1)
        # Row-major index of (4,4) on 9x9.
        self.assertEqual(snap["board_state_string"][4 * 9 + 4], ".")

        # JSON snapshot at move 1 (post-move): the stone is there.
        snap1 = self._json(
            "/service/get-historical-state/",
            your_cookie=black_cookie,
            move_number="1",
        )
        self.assertEqual(snap1["last_move_x"], 4)
        self.assertEqual(snap1["last_move_y"], 4)
        self.assertEqual(snap1["board_state_string"][4 * 9 + 4], "b")

        # Out-of-range move numbers are rejected.
        r = self.client.post(
            "/service/get-historical-state/",
            data={"your_cookie": black_cookie, "move_number": "-5"},
        )
        self.assertFalse(r.json()["success"])


class RfcAddressTests(TestCase):
    """
    ``_rfc_address`` produces RFC-5322-valid recipient strings.

    Regression guard: Django 6's SMTP ``prep_address`` raises ``ValueError``
    on a display name containing specials (e.g. ``.``) when the name isn't
    quoted. The pre-fix implementation did raw ``f"{name} <{email}>"`` and
    blew up in production on a player named ``Pluribus .``.
    """

    def test_plain_name_passes_through(self) -> None:
        """A simple alphabetic name needs no quoting."""
        self.assertEqual(_rfc_address("Alice", "a@x.com"), "Alice <a@x.com>")

    def test_name_with_period_is_quoted(self) -> None:
        """A name containing ``.`` is wrapped in double quotes per RFC 5322."""
        addr = _rfc_address("Pluribus .", "someone.else@example.com")
        self.assertEqual(addr, '"Pluribus ." <someone.else@example.com>')
        # And the result round-trips through the stdlib parser.
        name, email = parseaddr(addr)
        self.assertEqual(name, "Pluribus .")
        self.assertEqual(email, "someone.else@example.com")

    def test_django_smtp_prep_address_accepts_specials(self) -> None:
        """Every flavor of tricky display name survives ``prep_address``."""
        backend = SmtpEmailBackend()
        for name in ["Alice", "Pluribus .", "Smith, Jr.", "O'Reilly", "Anne-Marie"]:
            with self.subTest(name=name):
                backend.prep_address(_rfc_address(name, "user@example.com"))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailIntegrationTests(TestCase):
    """
    Verify the email side-effects of gameplay events.

    Fixing broken email delivery is one of the two forcing functions for this
    migration, so these assertions guard against regressions in the
    ``notify_*`` call sites in ``go/game/email.py``.
    """

    def _json(self, path: str, **data: str | int) -> dict[str, t.Any]:
        """POST ``data`` to ``path`` and return the parsed JSON body."""
        r = self.client.post(path, data=data)
        self.assertEqual(r.status_code, 200, f"{path} -> {r.status_code}")
        return r.json()

    def test_create_game_sends_two_notification_emails(self) -> None:
        """Both players receive an invitation email at game creation."""
        mail.outbox.clear()
        self._json(
            "/service/create-game/",
            your_name="Alice",
            your_contact="alice@example.com",
            your_contact_type=CONST.Email_Contact,
            opponent_name="Bob",
            opponent_contact="bob@example.com",
            opponent_contact_type=CONST.Email_Contact,
            your_color=str(CONST.Black_Color),
            board_size_index="2",
            handicap_index="0",
            komi_index="0",
        )

        self.assertEqual(len(mail.outbox), 2, [m.subject for m in mail.outbox])
        recipients = {m.to[0] for m in mail.outbox}
        self.assertEqual(recipients, {"Alice <alice@example.com>", "Bob <bob@example.com>"})
        for m in mail.outbox:
            self.assertIn("GO", m.subject)
            # Every invitation must include a link to /play/<cookie>/.
            self.assertIn("/play/", m.body)

    def test_move_sends_opponent_notification(self) -> None:
        """After a move, the opponent (not the mover) is emailed."""
        # Arrange: create a game and drain the invitation emails.
        created = self._json(
            "/service/create-game/",
            your_name="Alice",
            your_contact="alice@example.com",
            your_contact_type=CONST.Email_Contact,
            opponent_name="Bob",
            opponent_contact="bob@example.com",
            opponent_contact_type=CONST.Email_Contact,
            your_color=str(CONST.Black_Color),
            board_size_index="2",
            handicap_index="0",
            komi_index="0",
        )
        alice_cookie = created["your_cookie"]
        mail.outbox.clear()

        # Act: Alice (Black) plays a move.
        self._json(
            "/service/make-this-move/",
            your_cookie=alice_cookie,
            current_move_number="0",
            move_x="4",
            move_y="4",
        )

        # Assert: exactly one email went out, to Bob, containing the move number.
        self.assertEqual(len(mail.outbox), 1)
        notice = mail.outbox[0]
        self.assertEqual(notice.to, ["Bob <bob@example.com>"])
        self.assertIn("Move #1", notice.subject)
        self.assertIn("/play/", notice.body)

    def test_opted_out_player_does_not_get_email(self) -> None:
        """A player with ``wants_email=False`` is not sent turn reminders."""
        created = self._json(
            "/service/create-game/",
            your_name="Alice",
            your_contact="alice@example.com",
            your_contact_type=CONST.Email_Contact,
            opponent_name="Bob",
            opponent_contact="bob@example.com",
            opponent_contact_type=CONST.Email_Contact,
            your_color=str(CONST.Black_Color),
            board_size_index="2",
            handicap_index="0",
            komi_index="0",
        )
        alice_cookie = created["your_cookie"]
        alice = Player.by_cookie(alice_cookie)
        assert alice is not None
        bob = alice.get_opponent()
        assert bob is not None

        # Bob opts out.
        bob.wants_email = False
        bob.contact_type = CONST.No_Contact
        bob.save()
        mail.outbox.clear()

        # Alice plays; Bob should receive nothing.
        self._json(
            "/service/make-this-move/",
            your_cookie=alice_cookie,
            current_move_number="0",
            move_x="4",
            move_y="4",
        )
        self.assertEqual(len(mail.outbox), 0)
