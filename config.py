"""Read environment settings shared by bot startup and feature services."""

import os
from zoneinfo import ZoneInfo

import discord
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DB_PATH = os.environ.get("DB_PATH", "counters.db")  # same DB file as before

# If configured, test-only commands are registered only in this Discord server.
_test_guild_id = os.environ.get("TEST_GUILD_ID")
TEST_GUILD = discord.Object(id=int(_test_guild_id)) if _test_guild_id else None

# --- Social credit ---------------------------------------------------------
# Credit uses reset at midnight New York time (EST/EDT). Override with
# CREDIT_TIMEZONE only when a different rollover timezone is intended.
CREDIT_TZ = ZoneInfo(os.environ.get("CREDIT_TIMEZONE", "America/New_York"))
CREDIT_COMMENT_MAX = 200
LEADERBOARD_PAGE_SIZE = 10