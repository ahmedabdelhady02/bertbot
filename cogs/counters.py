# FILE: cogs/counters.py
# Discord layer for counters: /reset and /list slash commands, the confirm button view,
# and autocomplete. No raw SQL here; it calls services/counters.py.

import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from services import counters
from utils import format_duration, join_lines, normalize


async def counter_autocomplete(interaction: discord.Interaction, current: str):
    # Autocomplete is a small database-backed convenience; it doesn't create counters.
    if interaction.guild_id is None:
        return []
    names = counters.search_names(interaction.guild_id, normalize(current))
    return [app_commands.Choice(name=n, value=n) for n in names]


class ConfirmNew(discord.ui.View):
    """Private confirmation UI used only when /reset names a counter not yet stored."""

    def __init__(self, user_id: int, guild_id: int, name: str, culprit: discord.abc.User):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id
        self.name = name
        self.culprit = culprit
        self.original: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Prevent other members from confirming or cancelling the command owner's action.
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Yes, start it", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        # Recheck after the delay: another command may have created it meanwhile.
        existing = counters.get_counter(self.guild_id, self.name)
        if existing:
            public = counters.reset_counter(self.guild_id, existing, self.culprit)
        else:
            counters.create_counter(self.guild_id, self.name, self.culprit.display_name)
            public = counters.fmt(self.name, self.culprit, 0)

        await interaction.response.edit_message(content="Done!", view=None)
        await interaction.followup.send(public, ephemeral=False)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled, nothing was created.", view=None)

    async def on_timeout(self):
        if self.original:
            try:
                await self.original.edit_original_response(
                    content="Timed out, nothing was created.", view=None
                )
            except discord.HTTPException:
                pass


class Counters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="reset", description="Reset a 'days since last ... reference' counter")
    @app_commands.describe(
        counter="The thing that was referenced (pick one or type a new one)",
        culprit="Who caused the reset",
    )
    @app_commands.autocomplete(counter=counter_autocomplete)
    @app_commands.guild_only()
    async def reset_command(
        self,
        interaction: discord.Interaction,
        counter: app_commands.Range[str, 1, 60],
        culprit: discord.Member,
    ):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        name = normalize(counter)
        if not name:
            await interaction.response.send_message("Counter name can't be empty.", ephemeral=True)
            return

        # Existing counters reset immediately; new names need explicit confirmation.
        row = counters.get_counter(guild_id, name)
        if row:
            await interaction.response.send_message(
                counters.reset_counter(guild_id, row, culprit)
            )
            return

        view = ConfirmNew(interaction.user.id, guild_id, name, culprit)
        await interaction.response.send_message(
            f"There's no **{name}** counter yet. Start a new one at 0 days, reset by {culprit.mention}?",
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        view.original = interaction

    @app_commands.command(name="list", description="Show all counters, or just one")
    @app_commands.describe(counter="Optional: show only this counter")
    @app_commands.autocomplete(counter=counter_autocomplete)
    @app_commands.guild_only()
    async def list_counters(self, interaction: discord.Interaction, counter: Optional[str] = None):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return

        no_pings = discord.AllowedMentions.none()
        now = int(time.time())

        # With a name, show one counter's history; without one, build the full list.
        if counter is not None:
            name = normalize(counter)
            row = counters.get_counter_details(guild_id, name) if name else None
            if not row:
                await interaction.response.send_message(
                    f"No counter named **{name or counter}**.",
                    ephemeral=True,
                    allowed_mentions=no_pings,
                )
                return

            stored_name, started_at, last_culprit, record, last_streak = row
            lines = [f"**{format_duration(now - started_at)}** since last {stored_name} reference"]
            if last_culprit:
                lines.append(f"Last reset by {last_culprit}")
            if last_streak is not None:
                lines.append(f"Previous streak: {format_duration(last_streak)}")
            record = max(record or 0, now - started_at)  # the running streak counts too
            if record:
                lines.append(f"Record: {format_duration(record)}")
            await interaction.response.send_message("\n".join(lines), allowed_mentions=no_pings)
            return

        # No argument: list everything
        rows = counters.list_all(guild_id)
        if not rows:
            await interaction.response.send_message(
                "No counters yet. Use `/reset` to start one.", ephemeral=True
            )
            return

        lines = []
        for name, started_at, culprit, record in rows:
            record = max(record or 0, now - started_at)  # the running streak counts too
            details = []
            if culprit:
                details.append(f"last reset by {culprit}")
            if record:
                details.append(f"record {format_duration(record)}")
            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"**{name}**: {format_duration(now - started_at)}{suffix}")
        await interaction.response.send_message(join_lines(lines), allowed_mentions=no_pings)


async def setup(bot: commands.Bot):
    await bot.add_cog(Counters(bot))