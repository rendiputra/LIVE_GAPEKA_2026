"""Record the H5 (TLM) and H6 (SRI) gate outcomes used by the Phase 5b report.

Report only. Applying a coordinate happens in ``data/config/station_overrides.yaml``
(human-authored), never here.

Usage:
    python -m pipeline.h5_h6
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import override_gate

OUT = Path("data/review/h5_h6_gate.json")

PROPOSALS = [
    {
        "code": "TLM",
        "lat": -6.257272,
        "lon": 107.111231,
        "snap_max_m": 300.0,
        "source": "human, map lookup (H5)",
        "outcome": None,  # filled from the gate
    },
    {
        "code": "SRI",
        "lat": -6.923724274475478,
        "lon": 109.57099433659796,
        "snap_max_m": 50.0,
        "source": "human coordinate; OSM node/1244940845 corroboration (H6)",
        "outcome": None,
    },
]


def main() -> int:
    results = []
    for proposal in PROPOSALS:
        gate = override_gate.evaluate(
            proposal["code"], proposal["lat"], proposal["lon"], proposal["snap_max_m"]
        )
        checks = gate["checks"]
        if gate["passes"]:
            outcome = "applied"
            note = "all gate conditions hold"
        elif checks.get("snap_ambiguous"):
            outcome = "proposal_only"
            note = (
                "nearest-edge snap and a nearby track disagree; applying the "
                "coordinate now would route on the wrong track"
            )
        else:
            outcome = "proposal_only"
            note = "gate failed"

        nearest = gate["triples"][0] if gate["triples"] else {}
        alt = gate["candidate_tracks"][0] if gate["candidate_tracks"] else None
        results.append(
            {
                "code": proposal["code"],
                "lat": proposal["lat"],
                "lon": proposal["lon"],
                "source": proposal["source"],
                "snap_max_m": proposal["snap_max_m"],
                "outcome": outcome,
                "note": note,
                "snap_m": gate["snap"]["distance_m"],
                "ratio": nearest.get("ratio"),
                "angle": nearest.get("turn_angle_deg"),
                "neighbours": gate["neighbours_used"],
                "checks": checks,
                "best_alternative_track": (
                    {
                        "way_id": alt["way_id"],
                        "snap_distance_m": alt["snap_distance_m"],
                        "passes": alt["passes"],
                        "ratio": alt["triples"][0]["ratio"] if alt["triples"] else None,
                    }
                    if alt
                    else None
                ),
            }
        )

    payload = {
        "note": (
            "H5/H6 rail-path gate outcomes. 'applied' means the coordinate is in "
            "data/config/station_overrides.yaml; 'proposal_only' means it is not."
        ),
        "ratio_limit": override_gate.RATIO_LIMIT,
        "turnback_max_angle_deg": override_gate.TURNBACK_MAX_ANGLE_DEG,
        "results": results,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    for row in results:
        print(
            f"  {row['code']}: {row['outcome']} snap {row['snap_m']} m "
            f"ratio {row['ratio']} angle {row['angle']} | {row['note']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
