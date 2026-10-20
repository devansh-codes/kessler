"""`kessler export`: write the static data products consumed by the site (contract: plan §8.4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rich.console import Console

from kessler import config
from kessler.export.manifest import build_manifest

console = Console(stderr=True)


class BudgetExceeded(RuntimeError):
    pass


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), default=str, allow_nan=False))


def check_budgets(out: Path) -> None:
    cfg = config.settings()["export"]
    total = 0
    for p in out.rglob("*"):
        if not p.is_file():
            continue
        size = p.stat().st_size
        total += size
        if p.name == "ephem.bin" and size > cfg["ephem_max_bytes"]:
            raise BudgetExceeded(f"{p} is {size:,} bytes > {cfg['ephem_max_bytes']:,}")
    if total > cfg["total_max_bytes"]:
        raise BudgetExceeded(f"data products total {total:,} bytes > {cfg['total_max_bytes']:,}")
    console.print(f"budget ok: {total / 1e6:.1f} MB total")


def run_export(warehouse: Path, build_dir: Path, out: Path) -> None:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    build_dir = Path(build_dir)
    # Derived products are written by `kessler build` into build_dir/site; copy them verbatim.
    site_src = build_dir / "site"
    if site_src.exists():
        shutil.copytree(site_src, out, dirs_exist_ok=True)
    check_budgets(out)
    write_json(out / "manifest.json", build_manifest(warehouse, out))
    console.print(f"exported to {out}")
