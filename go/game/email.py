"""
Transactional email helpers for game notifications.

Ported from ``EmailHelper`` in _old/go.py with the critical change that the
sender moves off the dead ``appspotmail.com`` domain (which Google sunset for
outbound mail, breaking delivery) to a custom-domain sender configured via
``DEFAULT_FROM_EMAIL``. Backend (SMTP / Postmark / Resend / SES) is picked up
from Django's ``EMAIL_BACKEND`` setting.
"""

from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage


def _game_url(cookie: str) -> str:
    """Return the absolute ``/play/<cookie>/`` URL for email links."""
    return f"{settings.BASE_URL}/play/{cookie}/"


def _rfc_address(name: str, email: str) -> str:
    """
    Return an RFC 5322 ``Name <email>`` address string.

    Uses ``email.utils.formataddr`` so display names containing specials
    (``.``, ``,``, ``@``, ...) get quoted — Django 6's SMTP backend rejects
    the raw concatenated form as a malformed phrase.
    """
    return formataddr((name, email))


def _send(subject: str, body: str, to: str) -> None:
    """Build and send an ``EmailMessage`` with the configured backend."""
    EmailMessage(subject=subject, body=body, to=[to]).send()


def notify_you_new_game(
    your_name: str,
    your_email: str,
    your_cookie: str,
    opponent_name: str,
    your_turn: bool,
) -> None:
    """Email the game creator that their new game has been set up."""
    body: list[str] = []
    body = [
        f"Hi {your_name},\n\n"
        f"You've started a game of Go with {opponent_name}. "
        f"You can see what's happening by visiting:\n\n{_game_url(your_cookie)}\n\n"
    ]
    body += [
        "Also, it's your turn to move first!"
        if your_turn
        else "Your opponent plays first; you'll get an email when it's your turn to move."
    ]
    body += [
        "\n\n",
        "------\n\n",
        "Update May 2026: you may notice this email comes from somewhere new.\n",
        "You may also notice that the domain name you play at has changed.\n",
        "Everything should keep working as before. Let me know how it goes! -Dave\n",
    ]
    _send(
        subject=f"[GO] You've started a game with {opponent_name}",
        body="".join(body),
        to=_rfc_address(your_name, your_email),
    )


def notify_opponent_new_game(
    your_name: str,
    opponent_name: str,
    opponent_email: str,
    opponent_cookie: str,
    your_turn: bool,
) -> None:
    """Email the invited opponent that a new game has been started for them."""
    body: list[str] = []
    body = [
        f"Hi {opponent_name},\n\n"
        f"{your_name} started a game of Go with you. "
        f"You can see what's happening by visiting:\n\n{_game_url(opponent_cookie)}\n\n"
    ]
    body += [
        "You'll get another email when it's your turn."
        if your_turn
        else "It's your turn to move, so get going!"
    ]
    body += [
        "\n\n",
        "------\n\n",
        "Update May 2026: you may notice this email comes from somewhere new.\n",
        "You may also notice that the domain name you play at has changed.\n",
        "Everything should keep working as before. Let me know how it goes! -Dave\n",
    ]
    _send(
        subject=f"[GO] {your_name} has invited you to play!",
        body="".join(body),
        to=_rfc_address(opponent_name, opponent_email),
    )


def notify_your_turn(
    your_name: str,
    your_email: str,
    your_cookie: str,
    opponent_name: str,
    move_message: str,
    move_number: int,
) -> None:
    """Email a player that it's their turn to move."""
    if move_message == "It's your turn to move.":
        body = f"It's your turn to make a move against {opponent_name}."
    else:
        body = move_message
    body += f" Just follow this link:\n\n{_game_url(your_cookie)}\n"
    _send(
        subject=f"[GO - Move #{move_number}] It's your turn against {opponent_name}",
        body=body,
        to=_rfc_address(your_name, your_email),
    )


def notify_scoring(
    your_name: str,
    your_email: str,
    your_cookie: str,
    opponent_name: str,
    *,
    you_are_done: bool = False,
    no_longer_done: bool = False,
    game_over: bool = False,
) -> None:
    """Email a player about a scoring-phase transition."""
    if game_over:
        body = "The game is over!"
    elif no_longer_done:
        body = f"{opponent_name} has continued scoring; you are no longer finished."
    elif you_are_done:
        body = f"{opponent_name} has finished scoring; you should do the same."
    else:
        body = f"It's time to score your game against {opponent_name}."
    body += f" Just follow this link:\n\n{_game_url(your_cookie)}\n"
    _send(
        subject=f"[GO - Scoring] Scoring against {opponent_name}",
        body=body,
        to=_rfc_address(your_name, your_email),
    )


def remind_player(
    player_name: str,
    player_email: str,
    player_cookie: str,
    opponent_name: str,
    move_number: int,
    is_scoring: bool,
) -> None:
    """Email a stale-game reminder to a player who hasn't moved in a while."""
    body: list[str] = []
    if is_scoring:
        subject = (
            f"[GO - Scoring] REMINDER: You are still scoring your game against {opponent_name}"
        )
        body = [
            f"Just a reminder that you are still scoring in your game against "
            f"{opponent_name}. You haven't done anything in over a week. To mark "
            f"dead stones or finish the game, just follow this link:\n\n"
            f"{_game_url(player_cookie)}\n"
        ]
    else:
        subject = (
            f"[GO - Move #{move_number}] REMINDER: It's still your turn against {opponent_name}"
        )
        body = [
            f"Just a reminder that it's still your turn to move against "
            f"{opponent_name}. Your last move was over a week ago. To make a move, "
            f"just follow this link:\n\n{_game_url(player_cookie)}\n"
        ]
    body += [
        "\n\n",
        "------\n\n",
        "Update May 2026: you may notice this email comes from somewhere new.\n",
        "You may also notice that the domain name you play at has changed.\n",
        "Everything should keep working as before. Let me know how it goes! -Dave\n",
    ]
    _send(subject=subject, body="".join(body), to=_rfc_address(player_name, player_email))
