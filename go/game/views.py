"""
Class-based views for the Game of Go.

Ported from the ``webapp2`` handler classes in _old/go.py. Each view below
corresponds to one of the 20 player-facing routes registered in the original
application (the 6 privileged ``/cron/*`` / ``/export/*`` / ``/_ah/warmup``
routes are not ported — see the plan at
``/Users/dave/.claude/plans/here-s-a-very-old-distributed-breeze.md``).

Shared utilities:
- ``_JsonMixin`` gives each JSON-returning view an ``_ok`` / ``_fail`` helper.
- ``_player_from_cookie`` extracts and validates the ``your_cookie`` POST field.
- All write paths call ``game.save_state(...)`` + ``game.save()`` so the
  JSONField-serialized state stays in sync.
"""

import html
import logging
import typing as t

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import email as mailer
from . import game_logic as gl
from . import validators
from .models import Game, Player

log = logging.getLogger(__name__)


# All POST service endpoints inherit ``_JsonMixin``; the old webapp2 handlers
# had no CSRF protection and the existing ``go.js`` doesn't send tokens, so we
# exempt every service view's ``dispatch``. A later refactor can add CSRF and
# teach the frontend to include tokens.


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@method_decorator(csrf_exempt, name="dispatch")
class _JsonMixin(View):
    """Base class for JSON service views: CSRF-exempt + response helpers."""

    def _ok(self, **payload: t.Any) -> JsonResponse:
        """Return a ``{success: True, flash: 'OK', ...payload}`` JSON response."""
        data: dict[str, t.Any] = {"success": True, "flash": "OK"}
        data.update(payload)
        return JsonResponse(data)

    def _fail(self, message: str = "Invalid input.", **extra: t.Any) -> JsonResponse:
        """Return a ``{success: False, flash: message, ...extra}`` JSON response."""
        data: dict[str, t.Any] = {"success": False, "flash": message}
        data.update(extra)
        return JsonResponse(data)


def _render_fail(request: HttpRequest, message: str) -> HttpResponse:
    """Render ``fail.html`` with the given message (HTML 200)."""
    return render(request, "game/fail.html", {"message": message})


def _player_from_cookie(request: HttpRequest) -> Player | None:
    """Look up the Player from the ``your_cookie`` POST field, or ``None``."""
    cookie = request.POST.get("your_cookie")
    if not cookie:
        return None
    return Player.by_cookie(cookie)


def _int_post(request: HttpRequest, name: str) -> int | None:
    """Parse ``request.POST[name]`` as an int, or return ``None`` on error."""
    raw = request.POST.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except TypeError, ValueError:
        return None


def _chat_author(cookie: str, black: Player, white: Player) -> str:
    """Return the friendly name for ``cookie`` given the two player handles."""
    if cookie == black.cookie:
        return black.get_friendly_name()
    if cookie == white.cookie:
        return white.get_friendly_name()
    return "?"


# ---------------------------------------------------------------------------
# Splash and game-creation form
# ---------------------------------------------------------------------------


class MainView(View):
    """Render the splash page."""

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render ``index.html``."""
        return render(request, "game/index.html", {})


class GetGoingView(View):
    """Render the game-creation form."""

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render ``get-going.html``."""
        return render(request, "game/get-going.html", {})


# ---------------------------------------------------------------------------
# Gameplay: play, history, SGF, options
# ---------------------------------------------------------------------------


class PlayGameView(View):
    """Render the live game board for a given player cookie."""

    def get(self, request: HttpRequest, cookie: str) -> HttpResponse:
        """Render ``play.html`` populated with the current state for ``cookie``."""
        player = Player.by_cookie(cookie)
        if not player:
            return _render_fail(request, "No game with that ID could be found.")

        game: Game = player.game
        black = game.get_black_player()
        white = game.get_white_player()
        opponent = player.get_opponent()
        if not (black and white and opponent):
            return _render_fail(request, "Game is missing a player; please try again later.")

        state = game.load_state()
        board = state.get_board()
        your_move = state.whose_move == player.color
        you_done = state.is_done_scoring(player.color)
        opp_done = state.is_done_scoring(opponent.color)
        you_win = state.is_winner(player.color)
        opp_wins = state.is_winner(opponent.color)
        by_resign = (you_win or opp_wins) and not state.has_scoring_data()
        last_move_x, last_move_y = state.get_last_move()

        items = {
            "your_cookie": cookie,
            "your_color": player.color,
            "you_are_black": player.color == gl.CONST.Black_Color,
            "black_name": black.get_friendly_name(),
            "white_name": white.get_friendly_name(),
            "board_size_index": board.get_size_index(),
            "board_state_string": board.get_state_string(),
            "black_stones_captured": state.get_black_stones_captured(),
            "white_stones_captured": state.get_white_stones_captured(),
            "your_move": your_move,
            "whose_move": state.whose_move,
            "your_name": player.get_friendly_name(),
            "opponent_name": opponent.get_friendly_name(),
            "opponent_contact": opponent.get_contact(),
            "opponent_contact_type": opponent.get_contact_type(),
            "last_move_message": state.get_last_move_message(),
            "wants_email": "true" if player.wants_email else "false",
            "wants_email_python": player.wants_email,
            "current_move_number": game.get_current_move_number(),
            "last_move_x": last_move_x,
            "last_move_y": last_move_y,
            "last_move_was_pass": "true" if state.get_last_move_was_pass() else "false",
            "last_move_was_pass_python": state.get_last_move_was_pass(),
            "has_last_move": last_move_x != -1,
            "game_is_scoring": "true" if game.is_scoring() else "false",
            "game_is_scoring_python": game.is_scoring(),
            "you_are_done_scoring": "true" if you_done else "false",
            "you_are_done_scoring_python": you_done,
            "opponent_done_scoring": "true" if opp_done else "false",
            "opponent_done_scoring_python": opp_done,
            "scoring_number": state.get_scoring_number(),
            "game_is_finished": "true" if game.is_finished else "false",
            "game_is_finished_python": game.is_finished,
            "game_in_progress": "true" if game.in_progress() else "false",
            "game_in_progress_python": game.in_progress(),
            "any_captures": (state.get_black_stones_captured() + state.get_white_stones_captured())
            > 0,
            "has_scoring_data": game.has_scoring_data,
            "black_territory": state.get_black_territory(),
            "white_territory": state.get_white_territory(),
            "you_win": "true" if you_win else "false",
            "you_win_python": you_win,
            "opponent_wins": "true" if opp_wins else "false",
            "opponent_wins_python": opp_wins,
            "by_resignation": "true" if by_resign else "false",
            "by_resignation_python": by_resign,
            "board_class": board.get_class(),
            "komi": board.get_komi(),
            "show_grid": "true" if player.show_grid else "false",
            "show_grid_python": player.show_grid,
            "row_names": board.get_row_names(),
            "column_names": board.get_column_names(),
            "board_width": board.get_width(),
            "board_height": board.get_height(),
        }
        return render(request, "game/play.html", items)


class _HistoryBase(View):
    """Shared rendering for the history page (with or without a move number)."""

    def _render(self, request: HttpRequest, cookie: str, move: int | None) -> HttpResponse:
        """Render ``history.html`` for ``cookie`` at optional historical ``move``."""
        player = Player.by_cookie(cookie)
        if not player:
            return _render_fail(request, "No game with that ID could be found.")

        game: Game = player.game
        black = game.get_black_player()
        white = game.get_white_player()
        if not (black and white):
            return _render_fail(
                request, "Found a reference to a player, but couldn't find the game."
            )

        max_move_number = len(game.history)
        if move is None or move >= max_move_number or move < 0:
            state = game.load_state()
        else:
            state = game.load_history_state(move)

        board = state.get_board()
        last_move_x, last_move_y = state.get_last_move()
        items = {
            "your_cookie": cookie,
            "your_color": player.color,
            "board_size_index": board.get_size_index(),
            "board_state_string": board.get_state_string(),
            "white_stones_captured": state.get_white_stones_captured(),
            "black_stones_captured": state.get_black_stones_captured(),
            "current_move_number": state.current_move_number,
            "max_move_number": max_move_number,
            "last_move_message": state.get_last_move_message(),
            "last_move_x": last_move_x,
            "last_move_y": last_move_y,
            "last_move_was_pass": "true" if state.get_last_move_was_pass() else "false",
            "whose_move": state.whose_move,
            "white_name": white.get_friendly_name(),
            "black_name": black.get_friendly_name(),
            "board_class": board.get_class(),
            "you_are_black": player.color == gl.CONST.Black_Color,
            "show_grid": "true" if player.show_grid else "false",
            "show_grid_python": player.show_grid,
            "row_names": board.get_row_names(),
            "column_names": board.get_column_names(),
            "board_width": board.get_width(),
            "board_height": board.get_height(),
        }
        return render(request, "game/history.html", items)


class HistoryView(_HistoryBase):
    """Render the history page at the most recent move."""

    def get(self, request: HttpRequest, cookie: str) -> HttpResponse:
        """Render ``history.html`` for the given cookie at the latest move."""
        return self._render(request, cookie, None)


class HistoryMoveView(_HistoryBase):
    """Render the history page at a specific move number."""

    def get(self, request: HttpRequest, cookie: str, move: int) -> HttpResponse:
        """Render ``history.html`` for the given cookie at move ``move``."""
        return self._render(request, cookie, move)


class SGFView(View):
    """Return the full game history as an SGF file."""

    def get(self, request: HttpRequest, cookie: str) -> HttpResponse:
        """Stream back an SGF encoding of the whole game."""
        player = Player.by_cookie(cookie)
        if not player:
            return _render_fail(request, "No game with that ID could be found.")

        game: Game = player.game
        black = game.get_black_player()
        white = game.get_white_player()
        if not (black and white):
            return _render_fail(request, "Game is missing a player; please try again later.")

        current = game.load_state()
        board = current.get_board()
        handicap = board.get_handicap()
        handicap_stones = [gl.pos_to_coord(p) for p in board.get_handicap_positions()]

        chats: dict[int, list[str]] = {}
        for entry in game.load_chat():
            move_num = max(entry.get_move_number(), 1)
            chats.setdefault(move_num, []).append(
                f"{_chat_author(entry.get_cookie(), black, white)}: {entry.get_message()}"
            )

        all_states: list[gl.GameState] = [
            gl.GameState.from_jsonable(raw) for raw in game.history
        ] + [current]

        moves: list[str] = []
        mover = " BW"
        move_number = -1
        whose_move = all_states[0].get_whose_move() if all_states else gl.CONST.Black_Color

        for state in all_states[1:]:
            move_number_str = ""
            if state.get_current_move_number() != move_number + 1:
                move_number_str = f"MN[{state.get_current_move_number()}]"
            move_number = state.get_current_move_number()
            comment = f"C[{chr(10).join(chats[move_number])}]" if move_number in chats else ""
            letter = mover[whose_move]
            if state.get_last_move_was_pass():
                moves.append(f"{move_number_str}{letter}[]{comment}")
            else:
                moves.append(
                    f"{move_number_str}{letter}[{gl.pos_to_coord(state.get_last_move())}]{comment}"
                )
            whose_move = state.get_whose_move()

        items = {
            "base_url": settings.GO_BASE_URL,
            "start_date": game.date_created.date().isoformat(),
            "stop_date": game.date_last_moved.date().isoformat(),
            "board_size": board.get_width(),
            "komi": board.get_komi(),
            "handicap": handicap,
            "handicap_stones": handicap_stones,
            "white_name": white.get_friendly_name(),
            "black_name": black.get_friendly_name(),
            "moves": moves,
        }
        return render(request, "game/game.sgf", items, content_type="application/x-go-sgf")


class OptionsView(View):
    """Render the per-game options form."""

    def get(self, request: HttpRequest, cookie: str) -> HttpResponse:
        """Render ``options.html`` with the current contact settings."""
        player = Player.by_cookie(cookie)
        if not player:
            return _render_fail(request, "No game with that ID could be found.")
        items = {
            "your_cookie": cookie,
            "your_email": player.get_safe_email(),
            "your_contact_type": player.get_active_contact_type(),
        }
        return render(request, "game/options.html", items)


# ---------------------------------------------------------------------------
# Game creation
# ---------------------------------------------------------------------------


class CreateGameView(_JsonMixin, View):
    """Service endpoint: create a new game between two players."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Validate the form, create the game + two players, send notifications."""
        try:
            your_name = request.POST.get("your_name")
            your_contact = request.POST.get("your_contact")
            opponent_name = request.POST.get("opponent_name")
            opponent_contact = request.POST.get("opponent_contact")
            your_color_raw = request.POST.get("your_color")
            board_size_raw = request.POST.get("board_size_index")
            handicap_raw = request.POST.get("handicap_index")
            komi_raw = request.POST.get("komi_index")
            your_contact_type = request.POST.get("your_contact_type")
            opponent_contact_type = request.POST.get("opponent_contact_type")
            if None in (your_color_raw, board_size_raw, handicap_raw, komi_raw):
                raise ValueError("missing required field")
            your_color = int(t.cast(str, your_color_raw))
            board_size_index = int(t.cast(str, board_size_raw))
            handicap_index = int(t.cast(str, handicap_raw))
            komi_index = int(t.cast(str, komi_raw))
        except TypeError, ValueError:
            return self._fail()

        if your_color < gl.CONST.Black_Color or your_color > gl.CONST.White_Color:
            return self._fail("Invalid color.")
        if board_size_index < 0 or board_size_index >= len(gl.CONST.Board_Sizes):
            return self._fail("Invalid board size.")
        if handicap_index < 0 or handicap_index >= len(gl.CONST.Handicaps):
            return self._fail("Invalid handicap.")
        if komi_index < 0 or komi_index >= len(gl.CONST.Komis):
            return self._fail("Invalid komi.")
        if not validators.is_valid_name(your_name):
            return self._fail("Your name is invalid.")
        if not validators.is_valid_contact_type(your_contact_type):
            return self._fail("Your contact type is invalid.")
        if not validators.is_valid_contact_type(opponent_contact_type):
            return self._fail("Your opponent's contact type is invalid.")
        if not validators.is_valid_contact(your_contact, your_contact_type):
            return self._fail("Your contact information is invalid.")
        if not validators.is_valid_name(opponent_name):
            return self._fail("Your opponent's name is invalid.")
        if not validators.is_valid_contact(opponent_contact, opponent_contact_type):
            return self._fail("Your opponent's contact information is invalid.")

        try:
            your_cookie, _ = self._create_game(
                your_name=t.cast(str, your_name),
                your_email=t.cast(str, your_contact),
                opponent_name=t.cast(str, opponent_name),
                opponent_email=t.cast(str, opponent_contact),
                your_color=your_color,
                board_size_index=board_size_index,
                handicap_index=handicap_index,
                komi_index=komi_index,
            )
        except Exception:
            log.exception("CreateGameView failed")
            return self._fail(
                "Sorry, an unexpected error occurred. Please try again in a minute or two."
            )

        you = Player.by_cookie(your_cookie)
        assert you is not None
        your_turn = you.game.load_state().whose_move == your_color
        return JsonResponse(
            {
                "success": True,
                "your_cookie": your_cookie,
                "your_turn": your_turn,
                "flash": "OK",
            }
        )

    def _create_game(
        self,
        *,
        your_name: str,
        your_email: str,
        opponent_name: str,
        opponent_email: str,
        your_color: int,
        board_size_index: int,
        handicap_index: int,
        komi_index: int,
    ) -> tuple[str, str]:
        """Build and persist the Game and both Players, send emails."""

        def cookie_in_use(c: str) -> bool:
            return Player.objects.filter(cookie=c).exists()

        your_cookie, opponent_cookie = gl.GameCookie.unique_pair(cookie_in_use)

        board = gl.GameBoard(board_size_index, handicap_index, komi_index)
        state = gl.GameState()
        state.set_board(board)
        state.whose_move = (
            gl.CONST.Black_Color
            if gl.CONST.Handicaps[handicap_index] == 0
            else gl.CONST.White_Color
        )

        now = timezone.now()
        if your_color == gl.CONST.Black_Color:
            black_cookie, white_cookie = your_cookie, opponent_cookie
        else:
            black_cookie, white_cookie = opponent_cookie, your_cookie

        game = Game.objects.create(
            date_created=now,
            date_last_moved=now,
            reminder_send_time=now,
            current_state=state.to_jsonable(),
            history=[],
            chat_history=[],
            black_cookie=black_cookie,
            white_cookie=white_cookie,
        )

        Player.objects.create(
            game=game,
            cookie=your_cookie,
            color=your_color,
            name=your_name,
            email=your_email,
            wants_email=True,
            contact_type=gl.CONST.Email_Contact,
        )
        Player.objects.create(
            game=game,
            cookie=opponent_cookie,
            color=gl.opposite_color(your_color),
            name=opponent_name,
            email=opponent_email,
            wants_email=True,
            contact_type=gl.CONST.Email_Contact,
        )

        your_turn = your_color == state.whose_move
        mailer.notify_you_new_game(your_name, your_email, your_cookie, opponent_name, your_turn)
        mailer.notify_opponent_new_game(
            your_name, opponent_name, opponent_email, opponent_cookie, your_turn
        )
        return your_cookie, opponent_cookie


# ---------------------------------------------------------------------------
# Moves: play, pass, resign
# ---------------------------------------------------------------------------


class MakeThisMoveView(_JsonMixin, View):
    """Service endpoint: submit a new move."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Validate, apply the move, persist, and notify the opponent."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        if game.is_finished:
            return self._fail("No more moves can be made; the game is finished.")

        state = game.load_state()
        if state.whose_move != player.color:
            return self._fail("Sorry, but it is not your turn.")

        current_move = _int_post(request, "current_move_number")
        if current_move is None:
            return self._fail("Invalid current move number; refresh game board.")
        if current_move != game.get_current_move_number():
            return self._fail("Wrong move number; refresh stale game board.")

        move_x = _int_post(request, "move_x")
        move_y = _int_post(request, "move_y")
        if move_x is None or move_y is None:
            return self._fail("Invalid move x/y coordinate.")

        board = state.get_board()
        if not board.is_in_bounds(move_x, move_y):
            return self._fail("Move coordinates are out-of-bounds.")
        if board.get(move_x, move_y) != gl.CONST.No_Color:
            return self._fail("You can't move here; there is already a stone!")

        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(gl.opposite_color(player.color))
        new_state.set_last_move_was_pass(False)
        new_board = new_state.get_board()
        new_board.set(move_x, move_y, player.color)

        move_message = "It's your turn to move"
        ataris, captures = new_board.compute_atari_and_captures(move_x, move_y)
        if ataris > 0:
            move_message += (
                "; you were just placed in atari"
                if ataris == 1
                else "; you were just placed in double atari"
            )
        if captures:
            move_message += " and" if ataris else ";"
            move_message += (
                " one of your stones was captured"
                if len(captures) == 1
                else f" {len(captures)} of your stones were captured"
            )
            for cx, cy in captures:
                new_board.set(cx, cy, gl.CONST.No_Color)
            if player.color == gl.CONST.Black_Color:
                new_state.set_white_stones_captured(
                    new_state.get_white_stones_captured() + len(captures)
                )
            else:
                new_state.set_black_stones_captured(
                    new_state.get_black_stones_captured() + len(captures)
                )

        if new_board.is_stone_in_suicide(move_x, move_y):
            return self._fail("You can't move there; your stone would immediately be captured!")

        move_message += "."
        new_state.set_last_move_message(move_message)
        new_state.set_last_move(move_x, move_y)
        new_state_string = new_board.get_state_string()

        # Rule of Ko: new board state can't match the state from two moves ago
        # (the most recent entry in `history` BEFORE we append).
        if game.history:
            two_back = game.load_history_state(len(game.history) - 1)
            if two_back.get_board().get_state_string() == new_state_string:
                return self._fail(
                    "Sorry, but this move would violate the rule of Ko. "
                    "Move somewhere else and try playing here later!"
                )

        now = timezone.now()
        game.append_history(state)
        game.save_state(new_state)
        game.date_last_moved = now
        game.reminder_send_time = now
        game.save()

        opponent = player.get_opponent()
        if opponent and opponent.wants_email and opponent.email:
            mailer.notify_your_turn(
                opponent.get_friendly_name(),
                opponent.email,
                opponent.cookie,
                player.get_friendly_name(),
                move_message,
                new_state.get_current_move_number(),
            )

        return self._ok(
            flash="TODO",
            current_move_number=game.get_current_move_number(),
            white_stones_captured=new_state.get_white_stones_captured(),
            black_stones_captured=new_state.get_black_stones_captured(),
            board_state_string=new_state_string,
            last_move_x=move_x,
            last_move_y=move_y,
        )


class PassView(_JsonMixin, View):
    """Service endpoint: pass the turn."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Apply a pass and, if the previous move was also a pass, enter scoring."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        state = game.load_state()
        if state.whose_move != player.color:
            return self._fail("Sorry, but it is not your turn.")

        current_move = _int_post(request, "current_move_number")
        if current_move is None:
            return self._fail("Invalid current move number; refresh game board.")
        if current_move != game.get_current_move_number():
            return self._fail("Wrong move number; refresh stale game board.")

        new_state = state.clone()
        new_board = new_state.get_board()
        new_state.increment_current_move_number()
        new_state.set_whose_move(gl.opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        previous_also_passed = state.get_last_move_was_pass()
        if previous_also_passed:
            move_message = (
                "Mark the dead stones. Click done when finished. When you and "
                "your opponent agree, the game will end."
            )
            game.has_scoring_data = True
            new_state.increment_scoring_number()
            new_board.mark_territory()
            new_state.count_territory()
        else:
            move_message = (
                "Your opponent passed. You can make a move, or you can pass again to end the game."
            )
        new_state.set_last_move_message(move_message)

        now = timezone.now()
        game.append_history(state)
        game.save_state(new_state)
        game.date_last_moved = now
        game.reminder_send_time = now
        game.save()

        opponent = player.get_opponent()
        if opponent and opponent.wants_email and opponent.email:
            mailer.notify_your_turn(
                opponent.get_friendly_name(),
                opponent.email,
                opponent.cookie,
                player.get_friendly_name(),
                move_message,
                new_state.get_current_move_number(),
            )

        return self._ok(
            current_move_number=game.get_current_move_number(),
            board_state_string=new_board.get_state_string(),
            white_territory=new_state.get_white_territory(),
            black_territory=new_state.get_black_territory(),
            scoring_number=new_state.get_scoring_number(),
            game_is_scoring=game.is_scoring(),
            game_is_finished=game.is_finished,
        )


class ResignView(_JsonMixin, View):
    """Service endpoint: resign the game."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Mark the game finished with the opponent as the winner."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        state = game.load_state()
        if state.whose_move != player.color:
            return self._fail("Sorry, but it is not your turn.")

        current_move = _int_post(request, "current_move_number")
        if current_move is None:
            return self._fail("Invalid current move number; refresh game board.")
        if current_move != game.get_current_move_number():
            return self._fail("Wrong move number; refresh stale game board.")

        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(gl.opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        move_message = "The game is over!"
        game.is_finished = True
        new_state.set_winner(gl.opposite_color(player.color))
        new_state.set_last_move_message(move_message)

        now = timezone.now()
        game.append_history(state)
        game.save_state(new_state)
        game.date_last_moved = now
        game.reminder_send_time = now
        game.save()

        opponent = player.get_opponent()
        if opponent and opponent.wants_email and opponent.email:
            mailer.notify_your_turn(
                opponent.get_friendly_name(),
                opponent.email,
                opponent.cookie,
                player.get_friendly_name(),
                move_message,
                new_state.get_current_move_number(),
            )

        return self._ok(
            current_move_number=game.get_current_move_number(),
            game_is_scoring=game.is_scoring(),
            game_is_finished=game.is_finished,
        )


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


class HasOpponentMovedView(_JsonMixin, View):
    """Service endpoint: poll whether the opponent has moved since last sync."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Return whether the opponent has played and, if so, the new state."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        state = game.load_state()
        if state.whose_move != player.color:
            return self._ok(has_opponent_moved=False)

        board = state.get_board()
        opponent = player.get_opponent()
        last_move_x, last_move_y = state.get_last_move()
        return self._ok(
            has_opponent_moved=True,
            board_state_string=board.get_state_string(),
            white_stones_captured=state.get_white_stones_captured(),
            black_stones_captured=state.get_black_stones_captured(),
            current_move_number=game.get_current_move_number(),
            last_move_message=state.get_last_move_message(),
            last_move_x=last_move_x,
            last_move_y=last_move_y,
            last_move_was_pass=state.get_last_move_was_pass(),
            white_territory=state.get_white_territory(),
            black_territory=state.get_black_territory(),
            scoring_number=state.get_scoring_number(),
            you_win=state.is_winner(player.color),
            opponent_wins=state.is_winner(opponent.color) if opponent else False,
            game_is_scoring=game.is_scoring(),
            game_is_finished=game.is_finished,
        )


class HasOpponentScoredView(_JsonMixin, View):
    """Service endpoint: poll whether the opponent has advanced scoring."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Return whether the opponent's scoring number changed or the game ended."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        if game.in_progress():
            return self._fail("Scoring is not allowed yet; the game is still in progress.")

        base_scoring = _int_post(request, "scoring_number")
        if base_scoring is None:
            return self._fail("Unexpected error: invalid scoring request")

        state = game.load_state()
        if state.get_scoring_number() == base_scoring and not game.is_finished:
            return self._ok(has_opponent_scored=False)

        board = state.get_board()
        opponent = player.get_opponent()
        return self._ok(
            has_opponent_scored=True,
            board_state_string=board.get_state_string(),
            you_are_done_scoring=state.is_done_scoring(player.color),
            opponent_done_scoring=(state.is_done_scoring(opponent.color) if opponent else False),
            white_territory=state.get_white_territory(),
            black_territory=state.get_black_territory(),
            scoring_number=state.get_scoring_number(),
            you_win=state.is_winner(player.color),
            opponent_wins=state.is_winner(opponent.color) if opponent else False,
            game_is_finished=game.is_finished,
        )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class MarkStoneView(_JsonMixin, View):
    """Service endpoint: mark a stone dead/alive during scoring."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Toggle the owner of the connected group at the requested point."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        game: Game = player.game
        if game.is_finished:
            return self._fail("No more stones can be marked dead; the game is finished.")
        if game.in_progress():
            return self._fail("Scoring is not allowed yet; the game is still in progress.")

        state = game.load_state()
        if state.is_done_scoring(player.color):
            return self._fail("Sorry, but you have already finished scoring.")

        stone_x = _int_post(request, "stone_x")
        stone_y = _int_post(request, "stone_y")
        owner = _int_post(request, "owner")
        if stone_x is None or stone_y is None or owner is None:
            return self._fail("Invalid scoring x/y coordinate.")

        board = state.get_board()
        if not board.is_in_bounds(stone_x, stone_y):
            return self._fail("Stone coordinates are out-of-bounds.")

        piece_at = board.get(stone_x, stone_y)
        owner_at = board.get_owner(stone_x, stone_y)
        if piece_at == gl.CONST.No_Color:
            return self._fail("You can't mark an empty coordinate as dead or alive!")
        if owner == piece_at:
            color = gl.CONST.Color_Names[piece_at]
            return self._fail(f"Unexpected error: {color} stone cannot be {color} territory.")
        if owner == owner_at:
            return self._fail("Unexpected error: stone already marked as suggested.")

        new_state = state.clone()
        new_board = new_state.get_board()
        new_state.increment_scoring_number()
        stones = new_board.compute_changed_stones(stone_x, stone_y)
        if (stone_x, stone_y) not in stones:
            return self._fail("Unexpected error: marking stone had no effect.")

        for sx, sy in stones:
            new_board.set_owner(sx, sy, owner)
        new_board.mark_territory()
        new_state.count_territory()

        game.save_state(new_state)
        game.reminder_send_time = timezone.now()
        game.save()

        opponent = player.get_opponent()
        was_done = state.is_done_scoring(opponent.color) if opponent else False
        if was_done and opponent and opponent.wants_email and opponent.email:
            mailer.notify_scoring(
                opponent.get_friendly_name(),
                opponent.email,
                opponent.cookie,
                player.get_friendly_name(),
                no_longer_done=True,
            )

        return self._ok(
            flash="TODO",
            white_territory=new_state.get_white_territory(),
            black_territory=new_state.get_black_territory(),
            scoring_number=new_state.get_scoring_number(),
            board_state_string=new_board.get_state_string(),
        )


class DoneView(_JsonMixin, View):
    """Service endpoint: mark the current scoring round as finished."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Record the player done; if both done, end the game and pick a winner."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        done_scoring_number = _int_post(request, "scoring_number")
        if done_scoring_number is None:
            return self._fail()

        game: Game = player.game
        if game.is_finished:
            return self._fail("The game is already finished.")
        if game.in_progress():
            return self._fail("The game has not started scoring yet.")

        state = game.load_state()
        if state.is_done_scoring(player.color):
            return self._fail("You have already finished scoring.")

        if state.get_scoring_number() != done_scoring_number:
            flash = "Something has changed; review before clicking done."
            return self._render_success(game, player, state, flash)

        new_state = state.clone()
        new_state.set_done_scoring(player.color)
        if new_state.is_done_scoring():
            game.is_finished = True
            new_state.set_last_move_message("The game is over!")
            # Tie goes to White.
            if new_state.white_territory >= new_state.black_territory:
                new_state.set_winner(gl.CONST.White_Color)
            else:
                new_state.set_winner(gl.CONST.Black_Color)

        game.save_state(new_state)
        game.reminder_send_time = timezone.now()
        game.save()

        opponent = player.get_opponent()
        if opponent and opponent.wants_email and opponent.email:
            mailer.notify_scoring(
                opponent.get_friendly_name(),
                opponent.email,
                opponent.cookie,
                player.get_friendly_name(),
                you_are_done=True,
                game_over=game.is_finished,
            )

        return self._render_success(game, player, new_state, "OK")

    def _render_success(
        self,
        game: Game,
        player: Player,
        state: gl.GameState,
        flash: str,
    ) -> JsonResponse:
        """Build the scoring-phase JSON response matching the old handler."""
        opponent = player.get_opponent()
        board = state.get_board()
        return JsonResponse(
            {
                "success": True,
                "flash": flash,
                "board_state_string": board.get_state_string(),
                "you_are_done_scoring": state.is_done_scoring(player.color),
                "opponent_done_scoring": (
                    state.is_done_scoring(opponent.color) if opponent else False
                ),
                "white_territory": state.get_white_territory(),
                "black_territory": state.get_black_territory(),
                "scoring_number": state.get_scoring_number(),
                "you_win": state.is_winner(player.color),
                "opponent_wins": state.is_winner(opponent.color) if opponent else False,
                "game_is_finished": game.is_finished,
            }
        )


# ---------------------------------------------------------------------------
# Options (contact preferences + grid toggle)
# ---------------------------------------------------------------------------


class ChangeOptionsView(_JsonMixin, View):
    """Service endpoint: update a player's contact preferences."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Switch the player's ``contact_type`` and ``email`` per the form."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        new_contact_type = request.POST.get("new_contact_type")
        if not validators.is_valid_active_contact_type(new_contact_type):
            return self._fail("Unexpected error: invalid contact type.")

        new_contact = None
        if new_contact_type != gl.CONST.No_Contact:
            new_contact = request.POST.get("new_contact")
            if new_contact is None:
                return self._fail("Unexpected error: invalid contact.")

        if new_contact_type == gl.CONST.Email_Contact:
            if not validators.is_valid_email(new_contact):
                return self._fail("Invalid email address.")
            player.wants_email = True
            player.contact_type = gl.CONST.Email_Contact
            player.email = new_contact
        else:  # No_Contact
            player.wants_email = False
            player.contact_type = gl.CONST.No_Contact

        player.save()
        return self._ok()


class ChangeGridOptionsView(_JsonMixin, View):
    """Service endpoint: toggle the grid-display preference."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Set the player's ``show_grid`` to ``True`` or ``False``."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        raw = (request.POST.get("show_grid") or "").strip()
        if raw == "true":
            show = True
        elif raw == "false":
            show = False
        else:
            return self._fail("Unexpected error: invalid show_grid value.")

        player.show_grid = show
        player.save(update_fields=["show_grid"])
        return self._ok()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class RecentChatView(_JsonMixin, View):
    """Service endpoint: fetch chat messages newer than ``last_chat_seen``."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Return chat entries with index >= ``last_chat_seen``."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        last_seen = _int_post(request, "last_chat_seen")
        if last_seen is None:
            return self._fail("Unexpected error: try refreshing your browser window.")

        game: Game = player.game
        chats = game.load_chat()
        black = game.get_black_player()
        white = game.get_white_player()

        recent_payload = [
            {
                "name": (_chat_author(e.get_cookie(), black, white) if black and white else "?"),
                "message": e.get_message(),
                "move_number": e.get_move_number(),
            }
            for e in chats[last_seen:]
        ]
        return self._ok(chat_count=len(chats), recent_chats=recent_payload)


class AddChatView(_JsonMixin, View):
    """Service endpoint: append a chat message."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Append the POSTed ``message`` and return the new trailing chat window."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        message = request.POST.get("message")
        if message is None:
            return self._fail("Unexpected error: no message supplied.")
        message = message.strip()
        if len(message) > 140:
            message = message[:140] + "..."
        if not message:
            return JsonResponse({"success": True, "no_message": True, "flash": "OK"})
        clean = html.escape(message)

        last_seen = _int_post(request, "last_chat_seen")
        if last_seen is None:
            return self._fail("Unexpected error: try refreshing your browser window.")

        game: Game = player.game
        state = game.load_state()
        entry = gl.ChatEntry(player.cookie, clean, state.get_current_move_number())
        game.append_chat(entry)
        game.save(update_fields=["chat_history"])

        chats = game.load_chat()
        black = game.get_black_player()
        white = game.get_white_player()
        recent_payload = [
            {
                "name": (_chat_author(e.get_cookie(), black, white) if black and white else "?"),
                "message": e.get_message(),
                "move_number": e.get_move_number(),
            }
            for e in chats[last_seen:]
        ]
        return self._ok(chat_count=len(chats), recent_chats=recent_payload)


# ---------------------------------------------------------------------------
# Historical state (POST)
# ---------------------------------------------------------------------------


class GetHistoricalStateView(_JsonMixin, View):
    """Service endpoint: return the board state at a given historical move."""

    def post(self, request: HttpRequest) -> JsonResponse:
        """Return the JSON-ified state at ``move_number`` (or the current state)."""
        player = _player_from_cookie(request)
        if not player:
            return self._fail("Unexpected error: invalid player.")

        move_number = _int_post(request, "move_number")
        if move_number is None:
            return self._fail("Unexpected error: must specify a move number.")

        game: Game = player.game
        max_move = len(game.history)
        if move_number >= max_move:
            state = game.load_state()
        elif 0 <= move_number < max_move:
            state = game.load_history_state(move_number)
        else:
            return self._fail("Unexpected error: move number is out of range.")

        board = state.get_board()
        last_move_x, last_move_y = state.get_last_move()
        return self._ok(
            board_state_string=board.get_state_string(),
            white_stones_captured=state.get_white_stones_captured(),
            black_stones_captured=state.get_black_stones_captured(),
            current_move_number=state.current_move_number,
            max_move_number=max_move,
            last_move_message=state.get_last_move_message(),
            last_move_x=last_move_x,
            last_move_y=last_move_y,
            last_move_was_pass=state.get_last_move_was_pass(),
            whose_move=state.whose_move,
        )
