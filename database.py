import sqlite3

import config

# One shared connection for the whole bot (same file as before).
db = sqlite3.connect(config.DB_PATH)


def init_schema() -> None:
    """Create tables and run lightweight migrations. Safe to call on every start."""
    # Keep schema creation and forward-only migrations together so startup can
    # upgrade an existing database before the cogs begin serving commands.
    # --- counters ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS counters (
        guild_id            INTEGER,
        name                TEXT COLLATE NOCASE,
        started_at          INTEGER,
        last_culprit        TEXT,
        record_days         INTEGER DEFAULT 0,   -- legacy, no longer used
        last_streak_seconds INTEGER,
        record_seconds      INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, name)
    )""")
    # Migrate databases created before these columns existed
    cols = [r[1] for r in db.execute("PRAGMA table_info(counters)")]
    if "last_streak_seconds" not in cols:
        db.execute("ALTER TABLE counters ADD COLUMN last_streak_seconds INTEGER")
    if "record_seconds" not in cols:
        db.execute("ALTER TABLE counters ADD COLUMN record_seconds INTEGER DEFAULT 0")
        db.execute("UPDATE counters SET record_seconds = COALESCE(record_days, 0) * 86400")

    # --- social credit ---
    # A ledger: one row per vote. Scores are always SUM(delta), so they can't drift.
    # UNIQUE (guild_id, giver_id, day) enforces "one use per day" at the DB level,
    # which also makes it safe against double-clicks / concurrent commands.
    db.execute("""
    CREATE TABLE IF NOT EXISTS credit_votes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   INTEGER NOT NULL,
        giver_id   INTEGER NOT NULL,
        target_id  INTEGER NOT NULL,
        delta      INTEGER NOT NULL CHECK (delta IN (-1, 1)),
        comment    TEXT,
        day        TEXT NOT NULL,      -- YYYY-MM-DD in config.CREDIT_TZ
        created_at INTEGER NOT NULL,
        UNIQUE (guild_id, giver_id, day)
    )""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_credit_target "
        "ON credit_votes (guild_id, target_id)"
    )
    db.commit()