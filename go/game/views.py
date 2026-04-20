"""
Class-based views for the Game of Go.

Stub file. Views are ported from www/go.py one handler at a time in a later
task. Each class below corresponds to one of the webapp2 handlers registered
in www/go.py:3299-3326 and mirrors its URL in ``server/go/game/urls.py``.
"""

from django.http import HttpRequest, HttpResponse
from django.views import View


class _StubView(View):
    """Temporary placeholder used until each view is fully ported."""

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Return a 501 with the class name so unported routes surface loudly."""
        return HttpResponse(f"stub: {self.__class__.__name__}", status=501)


class MainView(_StubView):
    """Render the public splash page."""


class GetGoingView(_StubView):
    """Render the game-creation form."""


class PlayGameView(_StubView):
    """Render the live game board for the requesting player cookie."""


class SGFView(_StubView):
    """Return the full game history as an SGF file."""


class HistoryView(_StubView):
    """Render the per-game move-history browser."""


class HistoryMoveView(_StubView):
    """Render the board state at a specific historical move."""


class OptionsView(_StubView):
    """Render the per-game options form (notifications, grid display, etc.)."""


class CreateGameView(_StubView):
    """Service endpoint: create a new game."""


class MakeThisMoveView(_StubView):
    """Service endpoint: submit a new move."""


class HasOpponentMovedView(_StubView):
    """Service endpoint: poll whether the opponent has moved."""


class MarkStoneView(_StubView):
    """Service endpoint: toggle a stone as dead during scoring."""


class HasOpponentScoredView(_StubView):
    """Service endpoint: poll whether the opponent has finished scoring."""


class DoneView(_StubView):
    """Service endpoint: mark the current scoring round finished."""


class ChangeOptionsView(_StubView):
    """Service endpoint: update a player's game options."""


class ChangeGridOptionsView(_StubView):
    """Service endpoint: toggle grid display."""


class PassView(_StubView):
    """Service endpoint: pass the turn."""


class ResignView(_StubView):
    """Service endpoint: resign the game."""


class RecentChatView(_StubView):
    """Service endpoint: fetch recent chat messages."""


class AddChatView(_StubView):
    """Service endpoint: append a chat message."""


class GetHistoricalStateView(_StubView):
    """Service endpoint: return the board state at a given historical move."""
