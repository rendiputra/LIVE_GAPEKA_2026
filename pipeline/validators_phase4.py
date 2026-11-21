"""Phase 4 validators: V5 connectivity, V12 detour, V13 implied speed, V14 cumulative.

All four are report-only. None of them invents a value.

- V5  coverage of routed vs fallback vs unmeasured pairs, per trip.
- V12 detour ratio distribution; segments above the configured limit.
- V13 the **evidence** for Phase 5: implied average speed per timed hop compared
  with the printed maximum speed. The meaning of the printed column is not
  assumed; only the ratio is reported.
- V14 a trip's summed segment lengths must equal the route length the engine will
  use, and no segment between different stations may be zero or negative.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PARSED = Path("data/parsed")


def _seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


@dataclass
class RuleReport:
    rule: str
    description: str
    checked: int = 0
    findings: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "description": self.description,
            "checked": self.checked,
            "finding_count": len(self.findings),
            "findings": self.findings[:200],
            "details": self.details,
        }


def _segments_by_pair() -> dict[tuple[str, str], dict]:
    path = PARSED / "segments.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {(s["from_code"], s["to_code"]): s for s in payload["segments"]}


def _trips() -> list[dict]:
    out = []
    for book, name in ((1, "intercity_trips.json"), (2, "local_trips.json")):
        path = PARSED / name
        if not path.exists():
            continue
        for train in json.loads(path.read_text(encoding="utf-8"))["trains"]:
            train.setdefault("book", book)
            out.append(train)
    return out


def _lookup(segments: dict, a: str, b: str) -> dict | None:
    return segments.get((a, b)) or segments.get((b, a))


def validate_v5(trips: list[dict], segments: dict) -> RuleReport:
    report = RuleReport("V5", "share of pairs routed on OSM vs fallback vs unmeasured (per trip)")
    coverage: Counter[str] = Counter()
    non_routed: Counter[tuple[str, str]] = Counter()

    for train in trips:
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        counts: Counter[str] = Counter()
        for a, b in zip(codes, codes[1:], strict=False):
            if a == b:
                continue
            report.checked += 1
            segment = _lookup(segments, a, b)
            quality = segment["quality"] if segment else "unmeasured"
            counts[quality] += 1
            if quality in ("unmeasured", "straight_line"):
                non_routed[(a, b)] += 1
        total = sum(counts.values())
        if not total:
            continue
        if counts.get("unmeasured") == total:
            coverage["fully_unmeasured"] += 1
        elif counts.get("unmeasured") or counts.get("straight_line"):
            coverage["partial"] += 1
        else:
            coverage["fully_routed"] += 1

    report.details = {
        "pairs_checked": report.checked,
        "trips_by_coverage": dict(coverage),
        "non_routed_pairs": len(non_routed),
        "non_routed": [
            {"pair": f"{a}->{b}", "trips_affected": n}
            for (a, b), n in sorted(non_routed.items(), key=lambda kv: -kv[1])[:100]
        ],
    }
    return report


def validate_v12(trips: list[dict], segments: dict, threshold: float) -> RuleReport:
    report = RuleReport("V12", f"detour ratio distribution; list segments above {threshold}")
    ratios = []
    for (a, b), segment in segments.items():
        ratio = segment.get("detour_ratio")
        if ratio is None:
            continue
        report.checked += 1
        ratios.append(ratio)
        if ratio > threshold:
            report.findings.append(
                {
                    "pair": f"{a}->{b}",
                    "detour_ratio": ratio,
                    "straight_m": segment["straight_m"],
                    "length_m": segment["length_m"],
                }
            )
    ratios.sort()

    def q(p: float) -> float | None:
        if not ratios:
            return None
        return round(ratios[min(len(ratios) - 1, int(p * (len(ratios) - 1)))], 3)

    report.details = {
        "threshold": threshold,
        "min": ratios[0] if ratios else None,
        "p50": q(0.50),
        "p95": q(0.95),
        "p99": q(0.99),
        "max": ratios[-1] if ratios else None,
    }
    return report


def validate_v13(trips: list[dict], segments: dict, fast_kmh: float, slow_kmh: float) -> RuleReport:
    """V13: implied average speed vs the printed maximum.

    A "hop" is the run between two consecutive TIMED rows; the untimed rows in
    between are summed into the hop length, because the train still traverses
    them.
    """
    report = RuleReport(
        "V13", "implied average km/h per timed hop vs printed maximum (evidence only)"
    )
    ratios = []
    speeds = []

    for train in trips:
        stops = train["stops"]
        timed = [
            (i, s) for i, s in enumerate(stops) if s["arrive"]["value"] or s["depart"]["value"]
        ]
        for (i_a, a), (i_b, b) in zip(timed, timed[1:], strict=False):
            depart = _seconds(a["depart"]["value"])
            arrive = _seconds(b["arrive"]["value"])
            if depart is None or arrive is None:
                continue
            duration = arrive - depart
            if duration <= 0:
                duration += 24 * 3600
            if duration <= 0:
                continue

            # Length: this hop plus any untimed rows between the two.
            length = 0.0
            missing = False
            for j in range(i_a, i_b):
                left = stops[j]["station_code"]
                right = stops[j + 1]["station_code"]
                segment = _lookup(segments, left, right)
                if segment is None or segment["length_m"] is None:
                    missing = True
                    break
                length += segment["length_m"]
            if missing or length <= 0:
                continue

            report.checked += 1
            kmh = (length / 1000) / (duration / 3600)
            speeds.append(round(kmh, 1))

            printed = [
                int(s["speed"]["value"])
                for s in stops[i_a : i_b + 1]
                if s["speed"]["value"] and s["speed"]["value"].isdigit()
            ]
            if not printed:
                continue
            max_printed = max(printed)
            if max_printed <= 0:
                continue
            ratio = kmh / max_printed
            ratios.append(round(ratio, 3))
            if ratio > 1.0 or kmh > fast_kmh or kmh < slow_kmh:
                report.findings.append(
                    {
                        "train_no": train["train_no"],
                        "book": train["book"],
                        "from": a["station_code"],
                        "to": b["station_code"],
                        "seconds": duration,
                        "length_m": round(length, 1),
                        "avg_kmh": round(kmh, 1),
                        "printed_max": max_printed,
                        "ratio": round(ratio, 3),
                    }
                )

    report.findings.sort(key=lambda f: -f["ratio"])
    speeds.sort()
    ratios.sort()

    def q(values: list[float], p: float) -> float | None:
        if not values:
            return None
        return round(values[min(len(values) - 1, int(p * (len(values) - 1)))], 2)

    report.details = {
        "hops_measured": report.checked,
        "avg_kmh": {
            "min": speeds[0] if speeds else None,
            "p50": q(speeds, 0.50),
            "p95": q(speeds, 0.95),
            "max": speeds[-1] if speeds else None,
        },
        "ratio_avg_to_printed": {
            "p50": q(ratios, 0.50),
            "p95": q(ratios, 0.95),
            "p99": q(ratios, 0.99),
            "max": ratios[-1] if ratios else None,
        },
        "above_1_0": sum(1 for r in ratios if r > 1.0),
        "above_fast": sum(1 for s in speeds if s > fast_kmh),
        "below_slow": sum(1 for s in speeds if s < slow_kmh),
        "thresholds": {"fast_kmh": fast_kmh, "slow_kmh": slow_kmh},
    }
    return report


def validate_v14(trips: list[dict], segments: dict) -> RuleReport:
    """V14: summed lengths are complete and no usable segment is non-positive."""
    report = RuleReport(
        "V14", "summed segment lengths per trip are complete; no zero-length segments"
    )
    for (a, b), segment in segments.items():
        if a == b:
            continue
        report.checked += 1
        length = segment.get("length_m")
        if length is not None and length <= 0:
            report.findings.append({"pair": f"{a}->{b}", "length_m": length})

    incomplete = 0
    for train in trips:
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        for a, b in zip(codes, codes[1:], strict=False):
            if a == b:
                continue
            segment = _lookup(segments, a, b)
            if segment is None:
                incomplete += 1
    report.details = {"pairs_without_segment_row": incomplete}
    return report


def _polyline_length_m(coordinates: list[list[float]]) -> float:
    """Length of a [lon, lat] polyline."""
    from pipeline.rail_graph import haversine_m

    total = 0.0
    for first, second in zip(coordinates, coordinates[1:], strict=False):
        total += haversine_m((first[1], first[0]), (second[1], second[0]))
    return total


def validate_v14b(trips: list[dict], segments: dict, config: dict) -> RuleReport:
    """V14b: internal geometry consistency (gate for geometry-complete trips).

    a) each segment's polyline length equals its ``length_m`` within 1%
    b) hop joins are continuous within the snap tolerance + 50 m
    c) reversal symmetry: a segment used backwards has reversed coordinates
    d) no single point-to-point jump inside a segment exceeds the threshold
    e) a trip's assembled polyline equals the sum of its segment lengths within 1%
    """
    from pipeline.rail_graph import haversine_m, orient_geometry

    tolerance = config.get("v14b_jump_m", 5000.0)
    join_slack = config.get("v14b_join_slack_m", 50.0)
    report = RuleReport("V14b", "segment/trip polyline internal consistency")

    # (a) and (d) per segment
    segment_lengths: dict[tuple[str, str], float] = {}
    for (a, b), segment in sorted(segments.items()):
        coordinates = (segment.get("geometry") or {}).get("coordinates") or []
        if not coordinates or segment.get("length_m") is None:
            continue
        report.checked += 1
        poly = _polyline_length_m(coordinates)
        segment_lengths[(a, b)] = poly
        if segment["length_m"] > 0 and abs(poly - segment["length_m"]) / segment["length_m"] > 0.01:
            report.findings.append(
                {
                    "check": "a_polyline_vs_length",
                    "pair": f"{a}->{b}",
                    "length_m": segment["length_m"],
                    "polyline_m": round(poly, 1),
                }
            )
        # (d) is about the SPACING of digitised points inside a routed segment. A
        # straight_line fallback has exactly two points by definition, so its
        # length is not a "jump".
        if segment.get("quality") == "straight_line":
            continue
        worst = max(
            (
                haversine_m((p[1], p[0]), (q[1], q[0]))
                for p, q in zip(coordinates, coordinates[1:], strict=False)
            ),
            default=0.0,
        )
        if worst > tolerance:
            report.findings.append(
                {
                    "check": "d_point_jump",
                    "pair": f"{a}->{b}",
                    "jump_m": round(worst, 1),
                    "threshold_m": tolerance,
                }
            )

    # (c) reversal symmetry, property-checked on every segment
    for (a, b), segment in segments.items():
        coordinates = (segment.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        forward = orient_geometry(segment, segment["from_code"], segment["to_code"])
        backward = orient_geometry(segment, segment["to_code"], segment["from_code"])
        if forward != list(reversed(backward)):
            report.findings.append({"check": "c_reversal", "pair": f"{a}->{b}"})
        if backward[0] != forward[-1]:
            report.findings.append({"check": "c_reversal_end", "pair": f"{a}->{b}"})

    # (b) and (e) per trip
    trip_rows = []
    for train in trips:
        codes = [s["station_code"] for s in train["stops"] if s["station_code"]]
        # A trip is evaluated in RUNS of consecutive measured hops. An unmeasured
        # hop genuinely breaks the drawn line, so it must never be bridged by the
        # check (bridging produced a bogus 29 km "internal jump").
        assembled: list[list[float]] = []
        total = 0.0
        gaps = []
        previous_hop: tuple[str, str] | None = None
        runs: list[tuple[float, float]] = []  # (sum_m, polyline_m) per run
        for a, b in zip(codes, codes[1:], strict=False):
            segment = segments.get((a, b)) or segments.get((b, a))
            if not segment or not segment.get("length_m"):
                # Close the current run; the next measured hop starts a new one.
                if assembled and total > 0:
                    runs.append((total, _polyline_length_m(assembled)))
                assembled, total, previous_hop = [], 0.0, None
                continue
            oriented = orient_geometry(segment, a, b)
            if not oriented:
                previous_hop = None
                continue
            # Continuity is checked against the immediately preceding measured hop
            # only when no unmeasured hop sits between them.
            if assembled and previous_hop is not None:
                gap = haversine_m(
                    (assembled[-1][1], assembled[-1][0]), (oriented[0][1], oriented[0][0])
                )
                if gap > join_slack:
                    gaps.append({"from": a, "to": b, "gap_m": round(gap, 1)})
            assembled.extend(oriented)
            total += segment["length_m"]
            previous_hop = (a, b)

        if assembled and total > 0:
            runs.append((total, _polyline_length_m(assembled)))
        if not runs:
            continue
        total = sum(r[0] for r in runs)
        poly = sum(r[1] for r in runs)
        drift = abs(poly - total) / total
        trip_rows.append(
            {
                "train_no": train["train_no"],
                "book": train.get("book"),
                "sum_m": round(total, 1),
                "polyline_m": round(poly, 1),
                "drift": round(drift, 4),
            }
        )
        if gaps:
            report.findings.append(
                {
                    "check": "b_continuity",
                    "train_no": train["train_no"],
                    "gaps": gaps[:10],
                    "gap_count": len(gaps),
                }
            )
        if drift > 0.01:
            report.findings.append(
                {
                    "check": "e_trip_polyline",
                    "train_no": train["train_no"],
                    "sum_m": round(total, 1),
                    "polyline_m": round(poly, 1),
                    "drift": round(drift, 4),
                }
            )

    drifts = sorted(row["drift"] for row in trip_rows)
    report.details = {
        "thresholds": {"jump_m": tolerance, "join_slack_m": join_slack},
        "segments_checked": report.checked,
        "trips_checked": len(trip_rows),
        "drift": {
            "max": drifts[-1] if drifts else None,
            "p50": drifts[len(drifts) // 2] if drifts else None,
        },
        "worst_trips": sorted(trip_rows, key=lambda r: -r["drift"])[:10],
        "checks": {
            name: sum(1 for f in report.findings if f["check"] == name)
            for name in (
                "a_polyline_vs_length",
                "b_continuity",
                "c_reversal",
                "c_reversal_end",
                "d_point_jump",
                "e_trip_polyline",
            )
        },
    }
    return report


def run(config: dict) -> dict:
    segments = _segments_by_pair()
    trips = _trips()
    reports = [
        validate_v5(trips, segments),
        validate_v12(trips, segments, config["detour_suspect_ratio"]),
        validate_v13(
            trips, segments, config["implausible_fast_kmh"], config["implausible_slow_kmh"]
        ),
        validate_v14(trips, segments),
        validate_v14b(trips, segments, config),
    ]
    return {r.rule: r.as_dict() for r in reports}
