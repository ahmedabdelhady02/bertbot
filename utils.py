def format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    if total_seconds == 0:
        return "0 days"
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


def join_lines(lines: list[str], limit: int = 1900) -> str:
    """Join lines but stay under Discord's 2000-character message limit."""
    out, used = [], 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > limit:
            out.append(f"…and {len(lines) - i} more")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)