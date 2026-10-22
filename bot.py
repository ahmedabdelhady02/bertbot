"""Application entry point: configure the Discord bot and load its command cogs."""

import discord
from discord.ext import commands

import config
import database

EXTENSIONS = [
    "cogs.counters",
    "cogs.credit",
    "cogs.dev",  # only registers itself if TEST_GUILD_ID is set
]


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,  # slash commands only
            intents=discord.Intents.default(),
            help_command=None,
        )

    async def setup_hook(self):
        # Each cog owns one feature's Discord commands and is loaded as an extension.
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        # Global commands: every server the bot is in
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} global commands", flush=True)

        # Test-only commands: just the test server
        if config.TEST_GUILD:
            synced = await self.tree.sync(guild=config.TEST_GUILD)
            print(f"Synced {len(synced)} test-only commands to guild {config.TEST_GUILD.id}", flush=True)

    async def on_ready(self):
        print(f"Logged in as {self.user} (application id {self.application_id})", flush=True)
        for g in self.guilds:
            print(f"In guild: {g.name} ({g.id})", flush=True)
        print("Global commands:", [c.name for c in await self.tree.fetch_commands()], flush=True)
        if config.TEST_GUILD:
            print("Test guild commands:",
                  [c.name for c in await self.tree.fetch_commands(guild=config.TEST_GUILD)], flush=True)


def main():
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set (check your .env)")
    # Ensure tables and migrations are ready before any commands can use the DB.
    database.init_schema()
    Bot().run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()