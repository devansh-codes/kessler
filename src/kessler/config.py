"""Load the event registry, the pinned lockfile and settings."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class Reference(BaseModel):
    label: str
    time: datetime
    dv_ms: float | None = None


class Parent(BaseModel):
    norad: int | None = None
    name: str | None = None


class Event(BaseModel):
    id: str
    title: str
    parent: Parent
    intdes: str | None = None
    reference_time: datetime
    reference_precision_hours: float = 24
    reference_sources: list[Reference] = Field(default_factory=list)
    alt_references: list[Reference] = Field(default_factory=list)
    reference_note: str | None = None
    prior_breakups: list[str] = Field(default_factory=list)
    mode_hint: str | None = None
    regime: str = "LEO"
    stretch: bool = False
    blurb: str = ""
    # filled from the lockfile
    norad: int | None = None
    object_name: str | None = None


def load_events(config_dir: Path = CONFIG_DIR, include_stretch: bool = True) -> list[Event]:
    raw = yaml.safe_load((config_dir / "events.yaml").read_text())
    lock_path = config_dir / "events.lock.json"
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    events = []
    for e in raw["events"]:
        ev = Event(**e)
        pinned = lock.get(ev.id, {})
        ev.norad = pinned.get("norad", ev.parent.norad)
        ev.intdes = ev.intdes or pinned.get("intdes")
        ev.object_name = pinned.get("object_name")
        if include_stretch or not ev.stretch:
            events.append(ev)
    return events


def save_lock(entries: dict[str, dict[str, Any]], config_dir: Path = CONFIG_DIR) -> None:
    path = config_dir / "events.lock.json"
    lock = json.loads(path.read_text()) if path.exists() else {}
    lock.update(entries)
    path.write_text(json.dumps(lock, indent=2) + "\n")


@lru_cache
def settings(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    return yaml.safe_load((config_dir / "settings.yaml").read_text())
