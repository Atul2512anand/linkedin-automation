from __future__ import annotations

import sqlite3

from .config import load_config, project_path
from .util import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    company      TEXT NOT NULL DEFAULT '',
    location     TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    posted       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'new',
    notes        TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    first_name  TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',
    last_error  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);

CREATE TABLE IF NOT EXISTS actions (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    kind   TEXT NOT NULL,
    target TEXT NOT NULL,
    result TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_actions_kind_ts ON actions(kind, ts);
"""


def connect(cfg: dict | None = None) -> sqlite3.Connection:
    cfg = cfg or load_config()
    db_path = project_path(cfg["storage"]["database"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def log_action(
    con: sqlite3.Connection,
    kind: str,
    target: str,
    result: str,
    detail: str = "",
) -> None:
    con.execute(
        "INSERT INTO actions (ts, kind, target, result, detail) VALUES (?, ?, ?, ?, ?)",
        (now_iso(), kind, target, result, detail),
    )
    con.commit()


def count_actions(
    con: sqlite3.Connection,
    kind: str,
    result: str,
    since_iso: str,
) -> int:
    row = con.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE kind = ? AND result = ? AND ts >= ?",
        (kind, result, since_iso),
    ).fetchone()
    return int(row["n"])


def save_jobs(con: sqlite3.Connection, jobs: list[dict]) -> int:
    new_count = 0
    timestamp = now_iso()
    for job in jobs:
        cursor = con.execute(
            """
            INSERT OR IGNORE INTO jobs
                (job_id, title, company, location, url, posted, status, notes,
                 collected_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', '', ?, ?)
            """,
            (
                job["job_id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("url", ""),
                job.get("posted", ""),
                timestamp,
                timestamp,
            ),
        )
        new_count += cursor.rowcount
    con.commit()
    return new_count
