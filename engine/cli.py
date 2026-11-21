"""Engine CLI (Phase 5).

    python -m engine.cli at "2026-12-01T08:55:00+07:00" [--bbox minLon,minLat,maxLon,maxLat]
    python -m engine.cli trajectory --trip 249 --date 2026-12-01 --step 60

Read-only: it loads a snapshot and prints JSON/CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime

from engine.model import Policy
from engine.position import positions_at, trajectory
from engine.snapshot import load


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be minLon,minLat,maxLon,maxLat")
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gapeka position engine (read-only).")
    sub = parser.add_subparsers(dest="command", required=True)

    at_parser = sub.add_parser("at", help="positions at an instant")
    at_parser.add_argument("instant", help="ISO-8601 datetime, aware (e.g. +07:00)")
    at_parser.add_argument("--bbox", type=_parse_bbox, default=None)
    at_parser.add_argument("--show-fakultatif", action="store_true")
    at_parser.add_argument(
        "--geometry-policy",
        default="complete_and_estimated",
        choices=["complete_and_estimated", "complete_only", "allow_fallback"],
    )

    traj_parser = sub.add_parser("trajectory", help="one trip's trajectory as CSV")
    traj_parser.add_argument("--trip", required=True)
    traj_parser.add_argument("--date", required=True, help="service date YYYY-MM-DD")
    traj_parser.add_argument("--step", type=int, default=60)

    args = parser.parse_args(argv)
    snapshot = load()

    if args.command == "at":
        instant = datetime.fromisoformat(args.instant)
        policy = Policy(
            show_fakultatif=args.show_fakultatif,
            geometry_policy=args.geometry_policy,
        )
        positions = positions_at(snapshot, instant, policy)
        if args.bbox:
            min_lon, min_lat, max_lon, max_lat = args.bbox
            positions = [
                p for p in positions if min_lon <= p.lon <= max_lon and min_lat <= p.lat <= max_lat
            ]
        json.dump(
            {
                "instant": instant.isoformat(),
                "policy": policy.as_dict(),
                "snapshot": snapshot.as_dict(),
                "count": len(positions),
                "positions": [p.as_dict() for p in positions],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    frames = trajectory(snapshot, args.trip, date.fromisoformat(args.date), step_s=args.step)
    if not frames:
        print(f"no trajectory for trip {args.trip}", file=sys.stderr)
        return 1
    writer = csv.DictWriter(sys.stdout, fieldnames=list(frames[0].keys()))
    writer.writeheader()
    writer.writerows(frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
