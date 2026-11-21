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
    ]
    return {r.rule: r.as_dict() for r in reports}
