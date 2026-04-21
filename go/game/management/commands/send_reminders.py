"""
``python manage.py send_reminders``: email stale-game reminders.

Ported from ``SendRemindersHandler`` in _old/go.py. Invoked by ``dokku cron``
every 3 minutes; handles one stale game per run. A game is stale if its
``reminder_send_time`` is more than a week old. Games finished or abandoned
for more than two months have their reminder time pushed a year out.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...email import remind_player
from ...models import Game, Player


class Command(BaseCommand):
    """Send one stale-game reminder email per invocation."""

    help = "Send one stale-game reminder email per invocation."

    def handle(self, *args: object, **options: object) -> None:
        """Find one stale game and email its next-to-move player."""
        now = timezone.now()
        one_week_ago = now - timedelta(weeks=1)
        two_months_ago = now - timedelta(weeks=8)

        stale = (
            Game.objects.filter(reminder_send_time__lt=one_week_ago)
            .order_by("reminder_send_time")
            .first()
        )
        if stale is None:
            self.stdout.write("No stale games to remind about.")
            return

        if stale.is_finished:
            stale.dont_remind_for_long_time()
            self.stdout.write(f"Game {stale.id}: finished; suppressing future reminders.")
            return

        if stale.date_last_moved < two_months_ago:
            stale.dont_remind_for_long_time()
            self.stdout.write(f"Game {stale.id}: idle > 2 months; suppressing future reminders.")
            return

        state = stale.load_state()
        players: list[Player] = []
        if stale.is_scoring():
            for color_cookie in (stale.black_cookie, stale.white_cookie):
                p = Player.objects.filter(cookie=color_cookie).first()
                if p is not None and not state.is_done_scoring(p.color):
                    players.append(p)
        else:
            whose = stale.get_player_whose_move()
            if whose is None:
                stale.dont_remind_for_long_time()
                self.stdout.write(
                    f"Game {stale.id}: no current player; suppressing future reminders."
                )
                return
            players.append(whose)

        for player in players:
            opponent = player.get_opponent()
            if player.wants_email and player.email and opponent:
                remind_player(
                    player_name=player.get_friendly_name(),
                    player_email=player.email,
                    player_cookie=player.cookie,
                    opponent_name=opponent.get_friendly_name(),
                    move_number=state.get_current_move_number(),
                    is_scoring=stale.is_scoring(),
                )
                self.stdout.write(
                    f"Game {stale.id}: reminded {player.email} (cookie {player.cookie})."
                )
            else:
                self.stdout.write(
                    f"Game {stale.id}: player {player.cookie} opted out of notifications."
                )

        stale.reminder_send_time = now
        stale.save(update_fields=["reminder_send_time"])
