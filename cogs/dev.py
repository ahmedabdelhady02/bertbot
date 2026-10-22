import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.counters import counter_autocomplete
from services import counters, credit
from utils import normalize


class Dev(commands.Cog):
    """Test-only commands, registered only in TEST_GUILD."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="backdate",
        description="TEST ONLY: pretend a counter started N days ago",
    )
    @app_commands.autocomplete(counter=counter_autocomplete)
    async def backdate(self, interaction: discord.Interaction, counter: str, days: int):
        guild_id = interaction.guild_id
        row = counters.get_counter(guild_id, normalize(counter)) if guild_id is not None else None
        if guild_id is None or not row:
            await interaction.response.send_message("No such counter.", ephemeral=True)
            return
        counters.backdate(guild_id, row[0], days)
        await interaction.response.send_message(
            f"**{row[0]}** now started {days} days ago.", ephemeral=True
        )

    @app_commands.command(
        name="credit-reset-today",
        description="TEST ONLY: clear your own vote for today so you can vote again",
    )
    async def credit_reset_today(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        cleared = credit.clear_today(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            "Cleared today's vote." if cleared else "You haven't voted today.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    if config.TEST_GUILD:  # never registered if TEST_GUILD_ID isn't set
        await bot.add_cog(Dev(bot), guild=config.TEST_GUILD)