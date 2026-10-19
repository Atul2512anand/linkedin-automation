from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_start_iso() -> str:
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def week_start_iso() -> str:
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def random_pause(section: dict, label: str = "") -> None:
    low = float(section.get("min_pause_seconds", 2.0))
    high = float(section.get("max_pause_seconds", 4.0))
    wait_for(low, high, label)


def wait_for(low: float, high: float, label: str = "") -> None:
    seconds = random.uniform(low, high)
    if label:
        print(f"  [{label}] waiting {seconds:.0f}s")
    time.sleep(seconds)


def safe_format(template: str, values: dict) -> str:
    """Replace {placeholders} without raising on missing or stray braces."""
    def replace(match: re.Match) -> str:
        key = match.group(1)
        return str(values.get(key, "") or "")

    text = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template or "")
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, width: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def print_table(rows, headers, max_width: int = 42) -> None:
    if not rows:
        print("(none)")
        return
    data = []
    for row in rows:
        cells = []
        for header in headers:
            value = row[header] if not isinstance(row, dict) else row.get(header, "")
            cells.append(truncate(value, max_width))
        data.append(cells)

    widths = [len(h) for h in headers]
    for cells in data:
        widths = [max(w, len(c)) for w, c in zip(widths, cells)]

    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for cells in data:
        print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))
