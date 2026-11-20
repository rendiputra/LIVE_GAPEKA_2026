"""Environment doctor: report which optional tools are present.

Phase 3 gating requires the cross-check to have RUN, so a missing tool must be a
visible SKIPPED, never a silent pass. ``make doctor`` prints exactly what is
available.

Usage:
    python -m pipeline.doctor
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

MIN_PYTHON = (3, 12)


def _check_pdftotext() -> tuple[bool, str]:
    path = shutil.which("pdftotext")
    if path is None:
        return False, "not installed (macOS: brew install poppler)"
    try:
        proc = subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"present but unusable: {error}"
    version = (proc.stderr or proc.stdout).splitlines()[0] if (proc.stderr or proc.stdout) else ""
    return True, f"{path} ({version})"


def _check_import(module: str) -> tuple[bool, str]:
    try:
        imported = __import__(module)
    except ImportError:
        return False, "not installed (uv add --group dev " + module + ")"
    version = getattr(imported, "__version__", "unknown")
    return True, f"version {version}"


def _check_pdf(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing at {path} (keep it in data/input/, never commit)"
    size = path.stat().st_size
    return True, f"{path} ({size:,} bytes)"


def _check_network() -> tuple[bool, str]:
    """External sources are required for station coordinates (Phase 3a 4c)."""
    checks = {
        "wikidata": "https://query.wikidata.org/sparql",
        "osm": "https://overpass-api.de/api/status",
    }
    results = []
    for name, url in checks.items():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "live-gapeka/0.1"})
            with urllib.request.urlopen(request, timeout=25) as response:
                results.append(f"{name}:{response.status}")
        except Exception as error:  # noqa: BLE001 - report, never raise
            results.append(f"{name}:{type(error).__name__}")
    ok = all(":200" in item for item in results)
    return ok, " ".join(results)


def _check_raw_words(path: Path) -> tuple[bool, str]:
    manifest = path / "manifest.json"
    if not manifest.exists():
        return False, f"missing at {manifest} (run: make extract)"
    count = len(list(path.glob("page_*.json")))
    return True, f"{count} page files + manifest"


def main() -> int:
    rows: list[tuple[str, bool, str, bool]] = []

    version = sys.version_info
    ok_python = (version.major, version.minor) >= MIN_PYTHON
    rows.append(
        ("python >= 3.12", ok_python, f"{version.major}.{version.minor}.{version.micro}", True)
    )

    rows.append(("pymupdf", *_check_import("pymupdf"), True))
    rows.append(("pdfplumber (optional cross-check)", *_check_import("pdfplumber"), False))
    rows.append(("pdftotext (optional cross-check)", *_check_pdftotext(), False))
    rows.append(("Gapeka PDF", *_check_pdf(Path("data/input/GAPEKA_2026.pdf")), True))
    rows.append(("network (station coordinates)", *_check_network(), False))
    rows.append(("raw words", *_check_raw_words(Path("data/raw/words")), False))

    width = max(len(name) for name, *_ in rows)
    blocking_failures = []
    for name, ok, detail, required in rows:
        status = "OK" if ok else ("MISSING" if required else "SKIPPED")
        print(f"{name:<{width}}  {status:<8}  {detail}")
        if not ok and required:
            blocking_failures.append(name)

    optional_missing = [n for n, ok, _d, req in rows if not ok and not req]
    if optional_missing:
        print()
        print("Optional tools missing: " + ", ".join(optional_missing))
        print(
            "Cross-checks that need them will report SKIPPED, never a silent pass. "
            "Phase 3 gating requires the cross-check to have RUN."
        )

    return 1 if blocking_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
