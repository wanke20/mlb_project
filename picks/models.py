from django.conf import settings
from django.db import models

from games.models import Game, Team


class Pick(models.Model):
    """A user's winner pick for a single game.

    Picks are graded on the fly against the game's final score — we don't
    store a result column so re-fetched/corrected scores stay authoritative.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="picks"
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="picks")
    picked_team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="picks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One pick per user per game; changing a pick updates this row.
        constraints = [
            models.UniqueConstraint(fields=["user", "game"], name="unique_user_game_pick")
        ]
        ordering = ["-game__date", "-created_at"]

    def __str__(self):
        return f"{self.user} picked {self.picked_team} ({self.game})"

    @property
    def is_final(self):
        return self.game.home_score is not None and self.game.away_score is not None

    @property
    def winning_team(self):
        """The team that actually won, or None if the game isn't final / tied."""
        if not self.is_final:
            return None
        if self.game.home_score > self.game.away_score:
            return self.game.home_team
        if self.game.away_score > self.game.home_score:
            return self.game.away_team
        return None

    @property
    def status(self):
        """'pending', 'correct', or 'incorrect'."""
        winner = self.winning_team
        if winner is None:
            return "pending"
        return "correct" if winner == self.picked_team else "incorrect"
