"""Phase 1 validators: V1 times monotonic, V2 sane travel time, V3 station codes seen.

Only V1-V3 are implemented (Phase 1 scope). V4-V7 belong to Phase 2.

V3 uses a stations table built **only** from codes observed in the PDF
(``Name (CODE)`` pairs). No external master and no invented codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline import day_offsets
from pipeline.parsers.stop_table import ParsedTrain, Stop

# V2: inter-station travel time bounds. A dwell or run shorter than this is
# almost certainly a parse error; longer than this is implausible on Java.
MIN_TRAVEL_SECONDS = 30
MAX_TRAVEL_SECONDS = 8 * 3600


@dataclass
class Violation:
    rule: str
    train_no: str | None
    page: int | None
    seq: int | None
    station_code: str | None
    detail: str

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "train_no": self.train_no,
            "page": self.page,
            "seq": self.seq,
            "station_code": self.station_code,
            "detail": self.detail,
        }


@dataclass
class ValidationReport:
    rule: str
    description: str
    checked: int = 0
    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "description": self.description,
            "checked": self.checked,
            "passed": self.passed,
            "violation_count": len(self.violations),
            "violations": [v.as_dict() for v in self.violations],
        }


def _seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(p) for p in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _anchor_time(stop: Stop) -> tuple[str | None, str]:
    """The time a stop contributes to the sequence: departure if it stops, else pass time."""
    if stop.stop_type == "pass":
        return stop.depart.value, "depart"
    return stop.depart.value or stop.arrive.value, "depart" if stop.depart.value else "arrive"


def validate_v1(trains: list[ParsedTrain]) -> ValidationReport:
    """V1: times within a trip increase monotonically.

    Q3: a stop can arrive before midnight and depart after it, so each side uses
    its own day offset (``day_offsets.derive``). The anchor is the departure when
    one is printed, else the arrival. A decrease in absolute time is a real
    violation; the old "+24h rollover allowance" is gone because it hid rows whose
    day offset was wrong.
    """
    report = ValidationReport("V1", "times within a trip are monotonically increasing")
    for train in trains:
        previous = None
        for stop in train.stops:
            value, _kind = _anchor_time(stop)
            seconds = _seconds(value)
            if seconds is None:
                continue
            arrive_abs, depart_abs = day_offsets.absolute_times(
                getattr(stop.arrive, "value", stop.arrive),
                getattr(stop.depart, "value", stop.depart),
                stop.day_offset,
            )
            absolute = depart_abs if depart_abs is not None else arrive_abs
            if absolute is None:
                continue
            report.checked += 1
            if previous is not None:
                prev_absolute, prev_stop = previous
                if absolute < prev_absolute:
                    report.violations.append(
                        Violation(
                            rule="V1",
                            train_no=train.train_no,
                            page=stop.provenance.get("page"),
                            seq=stop.seq,
                            station_code=stop.station_code,
                            detail=(
                                f"absolute time went backwards: "
                                f"{prev_stop.seq}->{stop.seq} "
                                f"({_anchor_time(prev_stop)[0]} -> {value})"
                            ),
                        )
                    )
            previous = (absolute, stop)
    return report


def validate_v2(trains: list[ParsedTrain]) -> ValidationReport:
    """V2: inter-station travel time is positive and below a sane maximum."""
    report = ValidationReport("V2", "inter-station travel time within sane bounds")
    for train in trains:
        times: list[tuple[int, Stop, str]] = []
        for stop in train.stops:
            value, _kind = _anchor_time(stop)
            seconds = _seconds(value)
            if seconds is not None:
                times.append((seconds, stop, value))

        for (prev_s, prev_stop, prev_v), (cur_s, cur_stop, cur_v) in zip(
            times, times[1:], strict=False
        ):
            report.checked += 1
            delta = cur_s - prev_s
            if delta < 0:
                delta += 24 * 3600
            if delta < MIN_TRAVEL_SECONDS or delta > MAX_TRAVEL_SECONDS:
                report.violations.append(
                    Violation(
                        rule="V2",
                        train_no=train.train_no,
                        page=cur_stop.provenance.get("page"),
                        seq=cur_stop.seq,
                        station_code=cur_stop.station_code,
                        detail=(
                            f"{prev_stop.station_code}->{cur_stop.station_code} "
                            f"{prev_v} -> {cur_v} = {delta}s"
                        ),
                    )
                )
    return report


def validate_v3(trains: list[ParsedTrain], known_codes: set[str]) -> ValidationReport:
    """V3: every station code exists in the observed-codes table."""
    report = ValidationReport("V3", "every station_code exists in the stations table")
    for train in trains:
        for stop in train.stops:
            report.checked += 1
            if stop.station_code is None:
                report.violations.append(
                    Violation(
                        rule="V3",
                        train_no=train.train_no,
                        page=stop.provenance.get("page"),
                        seq=stop.seq,
                        station_code=None,
                        detail="station code not parsed from 'Name (CODE)'",
                    )
                )
            elif stop.station_code not in known_codes:
                report.violations.append(
                    Violation(
                        rule="V3",
                        train_no=train.train_no,
                        page=stop.provenance.get("page"),
                        seq=stop.seq,
                        station_code=stop.station_code,
                        detail="station code not present in the observed-codes table",
                    )
                )
    return report


def run_validators(trains: list[ParsedTrain], known_codes: set[str]) -> list[ValidationReport]:
    return [validate_v1(trains), validate_v2(trains), validate_v3(trains, known_codes)]
