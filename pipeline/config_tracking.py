"""Hash of every human-authored config file (P2).

Human decisions are code: they must be versioned and their exact content must be
identifiable. The hash of the tracked config files goes into the database build
metadata and every generated report, so two builds can be compared honestly.

Usage:
    python -m pipeline.config_tracking
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG_DIR = Path("data/config")

# Every human-authored config file that can change pipeline output. Missing files
# are ignored (a fresh checkout may not have them), so the hash describes what was
# actually used.
TRACKED = (
    "station_overrides.yaml",
    "station_aliases.yaml",
    "segment_reviews.yaml",
    "geometry_bridges.yaml",
    "snap_pins.yaml",
    "cell_markers.yaml",
    "geometry.yaml",
    "coverage.yaml",
)


def tracked_paths(config_dir: Path = CONFIG_DIR) -> list[Path]:
    return [config_dir / name for name in TRACKED]


def hash_paths(paths: list[Path]) -> str:
    """Deterministic hash over the given files: name + bytes, order independent."""
    digest = hashlib.sha256()
    for path, payload in sorted((path, path.read_bytes()) for path in paths if path.exists()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def config_hash(config_dir: Path = CONFIG_DIR) -> str:
    return hash_paths(tracked_paths(config_dir))


def manifest(config_dir: Path = CONFIG_DIR) -> dict:
    files = {}
    for path in tracked_paths(config_dir):
        if path.exists():
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"config_hash": config_hash(config_dir), "files": files}


def main() -> int:
    print(json.dumps(manifest(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
