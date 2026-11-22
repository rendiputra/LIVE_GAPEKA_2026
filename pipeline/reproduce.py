"""P2: prove the build reproduces from a clean clone.

Clones the repository into a temporary directory, copies the gitignored input
layers (parsed data, OSM extract, the PDF), rebuilds, and compares the three
hashes that must match:

- segments content hash
- database content hash
- tracked-config hash

Usage:
    python -m pipeline.reproduce
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INPUT_LAYERS = ("parsed", "external", "validated", "raw", "input")
FIELDS = ("segments_hash", "db_hash", "config_hash")


def local_hashes() -> dict:
    segments = json.loads(Path("data/parsed/segments.json").read_text(encoding="utf-8"))
    db = json.loads(Path("data/review/db_build.json").read_text(encoding="utf-8"))
    return {
        "segments_hash": segments["content_hash"],
        "db_hash": db["content_hash"],
        "config_hash": db["config"]["config_hash"],
    }


def run(cwd: Path, *args: str) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    expected = local_hashes()
    temp = Path(tempfile.mkdtemp(prefix="gapeka-repro-"))
    repo = temp / "repo"
    try:
        run(Path("."), "git", "clone", "--quiet", str(Path(".").resolve()), str(repo))
        for layer in INPUT_LAYERS:
            source = Path("data") / layer
            if source.exists():
                shutil.copytree(source, repo / "data" / layer, dirs_exist_ok=True)

        # build_db writes station_coordinates.json, which geometry reads.
        run(repo, "uv", "run", "python", "-m", "pipeline.build_db")
        run(repo, "uv", "run", "python", "-m", "pipeline.build_geometry")
        run(repo, "uv", "run", "python", "-m", "pipeline.build_db")

        actual = {
            "segments_hash": json.loads(
                (repo / "data/parsed/segments.json").read_text(encoding="utf-8")
            )["content_hash"],
            "db_hash": json.loads((repo / "data/review/db_build.json").read_text(encoding="utf-8"))[
                "content_hash"
            ],
            "config_hash": json.loads(
                (repo / "data/review/db_build.json").read_text(encoding="utf-8")
            )["config"]["config_hash"],
        }
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    ok = True
    for field in FIELDS:
        same = expected[field] == actual[field]
        ok = ok and same
        print(
            f"{'OK  ' if same else 'FAIL'} {field}: local {expected[field][:16]} "
            f"clone {actual[field][:16]}"
        )
    print("REPRODUCIBLE" if ok else "NOT REPRODUCIBLE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
