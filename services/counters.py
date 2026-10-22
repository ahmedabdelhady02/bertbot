# FILE: services/counters.py  (put in the services/ folder)
# Data layer for counters: all SQL and logic (get, create, reset, list, search).
# No slash commands here; cogs/counters.py calls into this.

import time

import discord

from database import db
from utils import format_duration


def fmt(name: str, culprit: discord.abc.User, elapsed_seconds: int = 0) -> str:
    return (
        f"**{format_duration(elapsed_seconds)}** since last {name} reference, "
        f"reset by {culprit.mention}"
    )


def get_counter(guild_id: int, name: str):
    """Fetch the compact row shape consumed by reset_counter."""
    return db.execute(
        "SELECT name, started_at, record_seconds, last_streak_seconds FROM counters "
        "WHERE guild_id = ? AND name = ?",
        (guild_id, name),
    ).fetchone()


def get_counter_details(guild_id: int, name: str):
    """Fetch the extra reset-history fields needed by /list for one counter."""
    return db.execute(
        "SELECT name, started_at, last_culprit, record_seconds, last_streak_seconds "
        "FROM counters WHERE guild_id = ? AND name = ?",
        (guild_id, name),
    ).fetchone()


def list_all(guild_id: int):
    return db.execute(
        "SELECT name, started_at, last_culprit, record_seconds FROM counters "
        "WHERE guild_id = ? ORDER BY name",
        (guild_id,),
    ).fetchall()


def search_names(guild_id: int, fragment: str) -> list[str]:
    rows = db.execute(
        "SELECT name FROM counters WHERE guild_id = ? AND name LIKE ? "
        "ORDER BY name LIMIT 25",
        (guild_id, f"%{fragment}%"),
    ).fetchall()
    return [r[0] for r in rows]


def create_counter(guild_id: int, name: str, culprit_name: str) -> None:
    db.execute(
        "INSERT INTO counters (guild_id, name, started_at, last_culprit) "
        "VALUES (?, ?, ?, ?)",
        (guild_id, name, int(time.time()), culprit_name),
    )
    db.commit()


def reset_counter(guild_id: int, row, culprit: discord.abc.User) -> str:
    """Reset an existing counter and return the public message."""
    # The row is the get_counter() tuple; preserve its record and prior streak
    # before writing the new start time and the streak that just ended.
    stored_name, started_at, record, previous_streak_seconds = row

    # Capture everything we need from the old state BEFORE overwriting it
    now = int(time.time())
    elapsed_seconds = max(0, now - started_at)  # the streak that just ended
    record = record or 0
    new_record = elapsed_seconds > record
    record = max(record, elapsed_seconds)

    db.execute(
        "UPDATE counters SET started_at = ?, last_culprit = ?, record_seconds = ?, "
        "last_streak_seconds = ? WHERE guild_id = ? AND name = ?",
        (now, culprit.display_name, record, elapsed_seconds, guild_id, stored_name),
    )
    db.commit()

    msg = fmt(stored_name, culprit, elapsed_seconds)
    if previous_streak_seconds is not None:
        msg += f"\nPrevious streak: {format_duration(previous_streak_seconds)}"
    if new_record:
        msg += f"\n🏆 New record: {format_duration(record)}!"
    elif record:
        msg += f"\nRecord: {format_duration(record)}"
    return msg


def backdate(guild_id: int, stored_name: str, days: int) -> None:
    """Test helper: pretend a counter started N days ago."""
    db.execute(
        "UPDATE counters SET started_at = ? WHERE guild_id = ? AND name = ?",
        (int(time.time()) - days * 86400, guild_id, stored_name),
    )
    db.commit()