"""Q3/Q5: Cloudflare R2 deploy helpers (dry-run by default).

Nothing here pushes to a live bucket unless ``--apply`` is given AND the required
environment variables are set. A dry run prints exactly what it would do.

Two things are uploaded separately, on purpose (ADR 009):

1. the static site (`web/dist/`) to the site bucket;
2. the PMTiles archive + glyphs/sprites to the tile bucket, which needs Range
   support and CORS.

Usage:
    python -m pipeline.deploy_r2 plan                 # print the plan, touch nothing
    python -m pipeline.deploy_r2 upload --dry-run     # show the wrangler commands
    python -m pipeline.deploy_r2 upload --apply       # actually upload
    python -m pipeline.deploy_r2 cors --dry-run       # show the CORS policy
    python -m pipeline.deploy_r2 rollback --dry-run   # show the rollback steps
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

DIST = Path("web/dist")
TILES = Path("web/public/tiles")
TILE_FILE = TILES / "java.pmtiles"
ASSETS = TILES / "assets"

SITE_BUCKET_ENV = "R2_SITE_BUCKET"
TILE_BUCKET_ENV = "R2_TILE_BUCKET"

# PMTiles is fetched with byte ranges, so these headers are mandatory.
CORS_POLICY = {
    "rules": [
        {
            "allowed": {
                "origins": ["https://YOUR-SITE-DOMAIN.example"],
                "methods": ["GET", "HEAD"],
                "headers": ["Range", "If-None-Match"],
            },
            "exposeHeaders": [
                "Content-Range",
                "Content-Length",
                "Accept-Ranges",
                "ETag",
            ],
            "maxAgeSeconds": 86400,
        }
    ]
}


def _wrangler() -> list[str] | None:
    """Return the wrangler command prefix, or None if unavailable.

    A local/global `wrangler` binary is preferred; otherwise `npx wrangler`, which
    is the documented way to run it without a global install.
    """
    binary = shutil.which("wrangler")
    if binary:
        return [binary]
    npx = shutil.which("npx")
    if npx:
        return [npx, "wrangler"]
    return None


def _bucket(env: str) -> str:
    import os

    return os.environ.get(env, "")


def plan() -> dict:
    """Describe what would be uploaded, with sizes. No side effects."""
    site_files = sorted(p for p in DIST.rglob("*") if p.is_file()) if DIST.exists() else []
    tile_files = sorted(p for p in TILES.rglob("*") if p.is_file()) if TILES.exists() else []
    return {
        "site_bucket_env": SITE_BUCKET_ENV,
        "tile_bucket_env": TILE_BUCKET_ENV,
        "site": {
            "root": str(DIST),
            "files": len(site_files),
            "bytes": sum(p.stat().st_size for p in site_files),
            "exists": DIST.exists(),
        },
        "tiles": {
            "root": str(TILES),
            "files": len(tile_files),
            "bytes": sum(p.stat().st_size for p in tile_files),
            "pmtiles_exists": TILE_FILE.exists(),
            "pmtiles_bytes": TILE_FILE.stat().st_size if TILE_FILE.exists() else 0,
        },
        "cors_policy": CORS_POLICY,
        "steps": [
            "1. upload web/dist/** to the SITE bucket (cache: index.html no-cache)",
            "2. upload java.pmtiles + assets/** to the TILE bucket with a dated name",
            "3. apply the CORS policy to the TILE bucket",
            "4. verify: curl -r 0-99 -o /dev/null -w '%{http_code}' <tiles-url> == 206",
            "5. point PMTILES_URL in web/src/config.ts at the tile URL and rebuild",
        ],
    }


def _run(command: list[str], dry_run: bool) -> int:
    print(("DRY-RUN " if dry_run else "RUN ") + " ".join(command))
    if dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


def upload(dry_run: bool) -> int:
    site_bucket = _bucket(SITE_BUCKET_ENV)
    tile_bucket = _bucket(TILE_BUCKET_ENV)
    if not dry_run and (not site_bucket or not tile_bucket):
        print(
            f"REFUSING: set {SITE_BUCKET_ENV} and {TILE_BUCKET_ENV} first.",
            file=sys.stderr,
        )
        return 2
    if not DIST.exists():
        print(f"REFUSING: {DIST} does not exist. Run `make web-build` first.", file=sys.stderr)
        return 2

    wrangler = _wrangler()
    if wrangler is None:
        print("REFUSING: wrangler not found (npm i -g wrangler).", file=sys.stderr)
        return 2

    site_bucket = site_bucket or "SITE_BUCKET"
    tile_bucket = tile_bucket or "TILE_BUCKET"

    code = _run(
        [
            *wrangler,
            "r2",
            "object",
            "put",
            f"{site_bucket}/index.html",
            "--file",
            str(DIST / "index.html"),
            "--content-type",
            '"text/html; charset=utf-8"',
            "--cache-control",
            "no-cache",
        ],
        dry_run,
    )
    if code != 0:
        return code

    assets = sorted(p for p in (DIST / "assets").glob("*") if p.is_file())
    for path in assets:
        suffix = path.suffix.lstrip(".")
        content_type = {"js": "text/javascript", "css": "text/css"}.get(
            suffix, "application/octet-stream"
        )
        code = _run(
            [
                *wrangler,
                "r2",
                "object",
                "put",
                f"{site_bucket}/assets/{path.name}",
                "--file",
                str(path),
                "--content-type",
                content_type,
                "--cache-control",
                "public, max-age=31536000, immutable",
            ],
            dry_run,
        )
        if code != 0:
            return code

    if TILE_FILE.exists():
        # Dated name: a new extract must never be masked by an old cache entry.
        manifest_path = TILES / "manifest.json"
        build = "unknown"
        if manifest_path.exists():
            build = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "build_date", "unknown"
            )
        code = _run(
            [
                *wrangler,
                "r2",
                "object",
                "put",
                f"{tile_bucket}/java-{build}.pmtiles",
                "--file",
                str(TILE_FILE),
                "--content-type",
                "application/octet-stream",
                "--cache-control",
                "public, max-age=31536000, immutable",
            ],
            dry_run,
        )
        if code != 0:
            return code

    for path in sorted(ASSETS.rglob("*")) if ASSETS.exists() else []:
        if not path.is_file():
            continue
        relative = path.relative_to(TILES)
        code = _run(
            [
                *wrangler,
                "r2",
                "object",
                "put",
                f"{tile_bucket}/{relative}",
                "--file",
                str(path),
                "--cache-control",
                "public, max-age=31536000, immutable",
            ],
            dry_run,
        )
        if code != 0:
            return code

    print("\nNext: apply the CORS policy, then verify a Range request returns 206.")
    return 0


def cors(dry_run: bool) -> int:
    tile_bucket = _bucket(TILE_BUCKET_ENV) or "TILE_BUCKET"
    print("CORS policy for the tile bucket:")
    print(json.dumps(CORS_POLICY, indent=2))
    print()
    print("Apply it in the Cloudflare dashboard (R2 > bucket > Settings > CORS),")
    print("or with the API:")
    print(
        f'  curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID'
        f'/r2/buckets/{tile_bucket}/cors" -H "Authorization: Bearer $CF_API_TOKEN"'
        f" -H 'Content-Type: application/json' --data @cors.json"
    )
    if dry_run:
        print("\nDRY-RUN: nothing was applied.")
    return 0


def rollback(dry_run: bool) -> int:
    """A static deploy rolls back by re-uploading the previous build."""
    print("Rollback procedure (no data migration is involved):")
    for step in (
        "1. keep every build in its own prefix, e.g. releases/<git-sha>/",
        "2. to roll back, re-upload the previous release's index.html + assets/",
        "3. tiles are immutable and dated, so they need no rollback unless the",
        "   extract itself was wrong; then repoint PMTILES_URL and rebuild",
        "4. verify: open the site, check the About dialog's data version hash",
        "5. verify tiles: curl -r 0-99 -o /dev/null -w '%{http_code}' <url> == 206",
    ):
        print(f"  {step}")
    if dry_run:
        print("\nDRY-RUN: nothing was changed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cloudflare R2 deploy helpers (dry-run by default)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    for name in ("upload", "cors", "rollback"):
        child = sub.add_parser(name)
        child.add_argument("--dry-run", action="store_true", default=False)
        child.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args(argv)

    if args.command == "plan":
        print(json.dumps(plan(), indent=2))
        return 0
    if args.command == "upload":
        return upload(dry_run=not args.apply)
    if args.command == "cors":
        return cors(dry_run=not args.apply)
    return rollback(dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
