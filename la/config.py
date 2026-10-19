from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_PATH = ROOT / "config.example.yaml"

DEFAULTS = {
    "browser": {
        "channel": "chrome",
        "profile_dir": "${LOCALAPPDATA}/linkedin-automation/browser-profile",
        "headless": False,
        "slow_mo_ms": 60,
        "locale": "en-US",
    },
    "storage": {
        "database": "data/automation.db",
        "screenshots": "data/screenshots",
        "exports": "data/exports",
    },
    "jobs": {
        "scrolls": 6,
        "pages": 3,
        "min_pause_seconds": 2.0,
        "max_pause_seconds": 4.0,
    },
    "outreach": {
        "enabled": False,
        "dry_run": True,
        "daily_cap": 10,
        "weekly_cap": 50,
        "min_delay_seconds": 45,
        "max_delay_seconds": 150,
        "working_hours": [10, 19],
        "send_connection_note": True,
        "note_max_chars": 200,
    },
    "templates": {
        "connection_note": (
            "Hi {first_name}, I'm exploring {role} roles at {company}. "
            "I'd value connecting and learning from your experience. Thanks!"
        ),
        "follow_up": (
            "Hi {first_name}, thanks for connecting. I'm actively looking for "
            "{role} roles at {company} - would you be open to a quick chat, or "
            "could you point me to the right person?"
        ),
    },
}


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict:
    config_path = Path(path) if path else CONFIG_PATH
    if not config_path.exists() and EXAMPLE_PATH.exists():
        shutil.copyfile(EXAMPLE_PATH, config_path)
    raw = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return _merge(DEFAULTS, raw)


def project_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    if path.is_absolute():
        return path.resolve()
    return (ROOT / path).resolve()
