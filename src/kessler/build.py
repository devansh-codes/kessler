"""`kessler build`: compute derived tables and site products from the warehouse."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


def run_build(warehouse: Path, build_dir: Path) -> None:
    Path(build_dir).mkdir(parents=True, exist_ok=True)
    console.print("build: nothing to compute yet")


def solve_event(warehouse: Path, event_id: str) -> dict:
    raise NotImplementedError
