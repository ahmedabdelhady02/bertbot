import os
import time
import sqlite3
import discord
from dotenv import load_dotenv
from discord import app_commands

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

db = sqlite3.connect("counters.db")
db.execute("""
CREATE TABLE IF NOT EXISTS counters (
    guild_id            INTEGER,
    name                TEXT COLLATE NOCASE,
    started_at          INTEGER,
    last_culprit        TEXT,
    record_days         INTEGER DEFAULT 0,
    last_streak_seconds INTEGER,
    PRIMARY KEY (guild_id, name)
)""")
# Migrate databases created before last_streak_seconds existed
_cols = [r[1] for r in db.execute("PRAGMA table_info(counters)")]
if "last_streak_seconds" not in _cols:
    db.execute("ALTER TABLE counters ADD COLUMN last_streak_seconds INTEGER")
db.commit()


def format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds or not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return ", ".join(parts)


def normalize(raw: str) -> str:
    """Collapse whitespace and drop a trailing 'reference' if the user typed it."""
    name = " ".join(raw.split())
    if name.lower().endswith(" reference"):
        name = name[: -len(" reference")].strip()
    return name


def fmt(name: str, culprit: discord.abc.User, elapsed_seconds: int = 0) -> str:
    return (
        f"**{format_duration(elapsed_seconds)}** since last {name} reference, "
        f"broken by {culprit.mention}"
    )


def get_counter(guild_id: int, name: str):
    return db.execute(
        "SELECT name, started_at, record_days, last_streak_seconds FROM counters "
        "WHERE guild_id = ? AND name = ?",
        (guild_id, name),
    ).fetchone()


def reset_counter(guild_id: int, row, culprit: discord.abc.User) -> str:
    """Reset an existing counter and return the public message."""
    stored_name, started_at, record, previous_streak_seconds = row

    # Capture everything we need from the old state BEFORE overwriting it
    now = int(time.time())
    elapsed_seconds = max(0, now - started_at)  # the streak that just ended
    streak_days = elapsed_seconds // 86400
    new_record = streak_days > record

    db.execute(
        "UPDATE counters SET started_at = ?, last_culprit = ?, record_days = ?, "
        "last_streak_seconds = ? WHERE guild_id = ? AND name = ?",
        (now, culprit.display_name, max(record, streak_days), elapsed_seconds,
         guild_id, stored_name),
    )
    db.commit()

    msg = fmt(stored_name, culprit, elapsed_seconds)
    if previous_streak_seconds is not None:
        msg += f"\nPrevious streak: {format_duration(previous_streak_seconds)}"
    if new_record:
        msg += "\n🏆 New record!"
    return msg


class ConfirmNew(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int, name: str, culprit: discord.Member):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id
        self.name = name
        self.culprit = culprit
        self.original: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Yes, start it", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        # Someone may have created it while the prompt was open
        existing = get_counter(self.guild_id, self.name)
        if existing:
            public = reset_counter(self.guild_id, existing, self.culprit)
        else:
            db.execute(
                "INSERT INTO counters (guild_id, name, started_at, last_culprit) "
                "VALUES (?, ?, ?, ?)",
                (self.guild_id, self.name, int(time.time()), self.culprit.display_name),
            )
            db.commit()
            public = fmt(self.name, self.culprit, 0)

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


class CounterBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    # async def setup_hook(self):
    #     await self.tree.sync()
    async def setup_hook(self):
        test_guild = os.environ.get("TEST_GUILD_ID")
        if test_guild:
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


bot = CounterBot()


async def counter_autocomplete(interaction: discord.Interaction, current: str):
    rows = db.execute(
        "SELECT name FROM counters WHERE guild_id = ? AND name LIKE ? "
        "ORDER BY name LIMIT 25",
        (interaction.guild_id, f"%{normalize(current)}%"),
    ).fetchall()
    return [app_commands.Choice(name=r[0], value=r[0]) for r in rows]


@bot.tree.command(name="break", description="Break a 'days since last ... reference' counter")
@app_commands.describe(
    counter="The thing that was referenced (pick one or type a new one)",
    culprit="Who broke it",
)
@app_commands.autocomplete(counter=counter_autocomplete)
@app_commands.guild_only()
async def break_counter(
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

    row = get_counter(guild_id, name)
    if row:
        await interaction.response.send_message(
            reset_counter(guild_id, row, culprit)
        )
        return

    view = ConfirmNew(interaction.user.id, guild_id, name, culprit)
    await interaction.response.send_message(
        f"There's no **{name}** counter yet. Start a new one at 0 days, broken by {culprit.mention}?",
        view=view,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    view.original = interaction


bot.run(os.environ["DISCORD_TOKEN"])