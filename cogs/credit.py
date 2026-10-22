# FILE: cogs/credit.py  (put in the cogs/ folder)
# Discord layer for social credit: /credit add, /credit subtract, /credit leaderboard
# (with paging buttons) and /credit view. No raw SQL here; it calls services/credit.py.

import math
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from services import credit
from utils import join_lines

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
NO_PINGS = discord.AllowedMentions.none()

Comment = Optional[app_commands.Range[str, 1, config.CREDIT_COMMENT_MAX]]


def signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


class LeaderboardView(discord.ui.View):
    """Prev/Next paging over the leaderboard. Only the person who ran the command can click."""

    def __init__(self, user_id: int, guild_id: int, lowest: bool):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.guild_id = guild_id
        self.lowest = lowest
        self.page = 0
        self.pages = 1
        self.original: discord.Interaction | None = None

    def render(self) -> discord.Embed:
        """Build the page embed and sync button state. Re-queries so data stays fresh."""
        size = config.LEADERBOARD_PAGE_SIZE
        total = credit.count_ranked(self.guild_id)
        self.pages = max(1, math.ceil(total / size))
        self.page = min(max(self.page, 0), self.pages - 1)

        rows = credit.leaderboard(
            self.guild_id, size, offset=self.page * size, lowest=self.lowest
        )

        title = "Social Credit: Lowest Scores" if self.lowest else "Social Credit Leaderboard"
        lines = []
        for user_id, score, rank in rows:
            medal = f" {MEDALS[rank]}" if not self.lowest and rank in MEDALS else ""
            lines.append(f"**{rank}. <@{user_id}>**{medal}")
            lines.append(f"> {score} credit")

        embed = discord.Embed(
            title=title,
            description=join_lines(lines),
            color=discord.Color.red() if self.lowest else discord.Color.gold(),
        )
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.pages} · {total} user{'s' if total != 1 else ''}"
        )

        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.pages - 1
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Run `/credit leaderboard` yourself to page through it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(
            embed=self.render(), view=self, allowed_mentions=NO_PINGS
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(
            embed=self.render(), view=self, allowed_mentions=NO_PINGS
        )

    async def on_timeout(self):
        # Leave the last page visible, just remove the buttons.
        if self.original:
            try:
                await self.original.edit_original_response(view=None)
            except discord.HTTPException:
                pass


class Credit(commands.Cog):
    credit = app_commands.Group(
        name="credit",
        description="Social credit",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----------------------------------------------------- add / subtract
    async def _cast(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        delta: int,
        comment: str | None,
    ):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return
        # Validate BEFORE casting so a rejected attempt doesn't burn the daily use.
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "You can't add or subtract social credit from yourself.", ephemeral=True
            )
            return
        if user.bot:
            await interaction.response.send_message(
                "Bots don't have social credit.", ephemeral=True
            )
            return

        comment = comment.strip() if comment else None

        try:
            score = credit.cast_vote(
                guild_id, interaction.user.id, user.id, delta, comment
            )
        except credit.AlreadyVoted as e:
            await interaction.response.send_message(
                f"You've already used your social credit today. Resets <t:{e.resets_at}:R>.",
                ephemeral=True,
            )
            return

        if delta > 0:
            msg = f"{interaction.user.mention} added **+1** social credit to {user.mention}."
        else:
            msg = f"{interaction.user.mention} subtracted **1** social credit from {user.mention}."
        if comment:
            msg += f"\n> {comment}"
        msg += f"\n{user.display_name}'s score: **{score}**"

        # Only the target can be pinged; the comment can never @everyone/@role.
        await interaction.response.send_message(
            msg, allowed_mentions=discord.AllowedMentions(users=[user])
        )

    @credit.command(name="add", description="Add +1 social credit to someone (1 use per day, shared with /credit subtract)")
    @app_commands.describe(user="Who should receive +1 social credit", comment="Optional reason")
    async def add(self, interaction: discord.Interaction, user: discord.Member, comment: Comment = None):
        await self._cast(interaction, user, +1, comment)

    @credit.command(name="subtract", description="Subtract 1 social credit from someone (1 use per day, shared with /credit add)")
    @app_commands.describe(user="Who should lose 1 social credit", comment="Optional reason")
    async def subtract(self, interaction: discord.Interaction, user: discord.Member, comment: Comment = None):
        await self._cast(interaction, user, -1, comment)

    # ----------------------------------------------------------- leaderboard
    @credit.command(name="leaderboard", description="Show the social credit leaderboard")
    @app_commands.describe(order="Highest scores (default) or lowest scores")
    @app_commands.choices(
        order=[
            app_commands.Choice(name="Highest", value="top"),
            app_commands.Choice(name="Lowest", value="bottom"),
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        order: Optional[app_commands.Choice[str]] = None,
    ):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return
        if credit.count_ranked(guild_id) == 0:
            await interaction.response.send_message(
                "No social credit has been added yet. Use `/credit add` or `/credit subtract` to start.",
                ephemeral=True,
            )
            return

        lowest = order is not None and order.value == "bottom"
        view = LeaderboardView(interaction.user.id, guild_id, lowest)
        embed = view.render()

        if view.pages <= 1:  # everything fits on one page, no buttons needed
            await interaction.response.send_message(embed=embed, allowed_mentions=NO_PINGS)
            return

        await interaction.response.send_message(embed=embed, view=view, allowed_mentions=NO_PINGS)
        view.original = interaction

    # ------------------------------------------------------------------ view
    @credit.command(name="view", description="See someone's score and recent comments")
    @app_commands.describe(user="Optional: defaults to you")
    async def view(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        score, ups, downs = credit.get_summary(guild_id, target.id)
        added, subtracted = credit.get_action_counts(guild_id, target.id)
        rank = credit.get_rank(guild_id, target.id)

        lines = [f"**{target.display_name}**: **{score}** social credit"]
        lines.append(f"Received: {ups} added, {downs} subtracted")
        lines.append(f"Added: {added} × +1, subtracted: {subtracted} × -1")
        lines.append(f"Rank: #{rank}" if rank else "Rank: unranked (no votes yet)")

        comments = credit.recent_comments(guild_id, target.id)
        if comments:
            lines.append("")
            lines.append("**Recent comments**")
            for giver_id, delta, text, created_at in comments:
                lines.append(f"{signed(delta)} from <@{giver_id}> (<t:{created_at}:d>): {text}")

        await interaction.response.send_message(join_lines(lines), allowed_mentions=NO_PINGS)


async def setup(bot: commands.Bot):
    await bot.add_cog(Credit(bot))