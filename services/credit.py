# FILE: services/credit.py  (put in the services/ folder)
# Data layer for social credit: casting votes, the one-per-day rule, scores, ranks,
# leaderboard queries. No slash commands here; cogs/credit.py calls into this.

import sqlite3
import time
from datetime import datetime, timedelta

import config
from database import db


class AlreadyVoted(Exception):
    """Raised when the voter has already used today's credit."""

    def __init__(self, resets_at: int):
        super().__init__("daily credit already used")
        self.resets_at = resets_at  # unix timestamp of the next reset


def _now() -> datetime:
    return datetime.now(config.CREDIT_TZ)


def today_key() -> str:
    # The stored day follows the configured local rollover, not UTC midnight.
    return _now().date().isoformat()


def next_reset_ts() -> int:
    now = _now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight + timedelta(days=1)).timestamp())


def cast_vote(
    guild_id: int, giver_id: int, target_id: int, delta: int, comment: str | None
) -> int:
    """Record a vote and return the target's new score.

    The UNIQUE (guild_id, giver_id, day) constraint is what enforces the daily
    limit, so two simultaneous commands can't both succeed.
    """
    try:
        db.execute(
            "INSERT INTO credit_votes "
            "(guild_id, giver_id, target_id, delta, comment, day, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, giver_id, target_id, delta, comment, today_key(), int(time.time())),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise AlreadyVoted(next_reset_ts())
    return get_score(guild_id, target_id)


def get_score(guild_id: int, user_id: int) -> int:
    row = db.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM credit_votes "
        "WHERE guild_id = ? AND target_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return row[0]


def get_summary(guild_id: int, user_id: int) -> tuple[int, int, int]:
    """Return (score, positive_votes, negative_votes) for a user."""
    row = db.execute(
        "SELECT COALESCE(SUM(delta), 0), "
        "       COALESCE(SUM(CASE WHEN delta > 0 THEN 1 ELSE 0 END), 0), "
        "       COALESCE(SUM(CASE WHEN delta < 0 THEN 1 ELSE 0 END), 0) "
        "FROM credit_votes WHERE guild_id = ? AND target_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return row[0], row[1], row[2]


def get_action_counts(guild_id: int, user_id: int) -> tuple[int, int]:
    """Return how many positive and negative votes this user has cast."""
    row = db.execute(
        "SELECT "
        "       COALESCE(SUM(CASE WHEN delta > 0 THEN 1 ELSE 0 END), 0), "
        "       COALESCE(SUM(CASE WHEN delta < 0 THEN 1 ELSE 0 END), 0) "
        "FROM credit_votes WHERE guild_id = ? AND giver_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return row[0], row[1]


def get_rank(guild_id: int, user_id: int) -> int | None:
    """1-based rank by score, or None if the user has never used the credit command."""
    if db.execute(
        "SELECT 1 FROM credit_votes "
        "WHERE guild_id = ? AND (target_id = ? OR giver_id = ?) LIMIT 1",
        (guild_id, user_id, user_id),
    ).fetchone() is None:
        return None
    score = get_score(guild_id, user_id)
    row = db.execute(
        "SELECT COUNT(*) + 1 FROM ("
        "  SELECT participants.user_id, COALESCE(SUM(votes.delta), 0) AS s "
        "  FROM ("
        "    SELECT target_id AS user_id FROM credit_votes WHERE guild_id = ? "
        "    UNION "
        "    SELECT giver_id AS user_id FROM credit_votes WHERE guild_id = ?"
        "  ) AS participants "
        "  LEFT JOIN credit_votes AS votes "
        "    ON votes.guild_id = ? AND votes.target_id = participants.user_id "
        "  GROUP BY participants.user_id"
        ") WHERE s > ?",
        (guild_id, guild_id, guild_id, score),
    ).fetchone()
    return row[0]


def count_ranked(guild_id: int) -> int:
    """Number of users who have ever used or received the credit command."""
    return db.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT target_id AS user_id FROM credit_votes WHERE guild_id = ? "
        "  UNION "
        "  SELECT giver_id AS user_id FROM credit_votes WHERE guild_id = ?"
        ")",
        (guild_id, guild_id),
    ).fetchone()[0]


def leaderboard(
    guild_id: int, limit: int, offset: int = 0, lowest: bool = False
) -> list[tuple[int, int, int]]:
    """Return one page of [(user_id, score, rank), ...], best-first (or worst-first if lowest).

    Includes anyone who has cast or received a vote; givers with no received votes
    have a score of 0. Users with tied scores share the same rank.
    """
    direction = "ASC" if lowest else "DESC"  # fixed strings only, never user input
    return db.execute(
        f"SELECT user_id, score, RANK() OVER (ORDER BY score {direction}) AS rank "
        f"FROM ("
        f"  SELECT participants.user_id, COALESCE(SUM(votes.delta), 0) AS score "
        f"  FROM ("
        f"    SELECT target_id AS user_id FROM credit_votes WHERE guild_id = ? "
        f"    UNION "
        f"    SELECT giver_id AS user_id FROM credit_votes WHERE guild_id = ?"
        f"  ) AS participants "
        f"  LEFT JOIN credit_votes AS votes "
        f"    ON votes.guild_id = ? AND votes.target_id = participants.user_id "
        f"  GROUP BY participants.user_id"
        f") "
        f"ORDER BY score {direction}, user_id LIMIT ? OFFSET ?",
        (guild_id, guild_id, guild_id, limit, offset),
    ).fetchall()


def recent_comments(guild_id: int, user_id: int, limit: int = 5):
    """Return [(giver_id, delta, comment, created_at), ...] newest first."""
    return db.execute(
        "SELECT giver_id, delta, comment, created_at FROM credit_votes "
        "WHERE guild_id = ? AND target_id = ? AND comment IS NOT NULL "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (guild_id, user_id, limit),
    ).fetchall()


def clear_today(guild_id: int, giver_id: int) -> bool:
    """Test helper: delete the giver's vote for today so they can vote again."""
    cur = db.execute(
        "DELETE FROM credit_votes WHERE guild_id = ? AND giver_id = ? AND day = ?",
        (guild_id, giver_id, today_key()),
    )
    db.commit()
    return cur.rowcount > 0