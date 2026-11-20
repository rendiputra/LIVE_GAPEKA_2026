"""Validators V10 (untimed pass rows) and V11 (sequence continuity).

Both are Phase 2 validated gates, in addition to V1/V2/V8.

V10 — an untimed pass row must sit strictly between two timed rows of the same
trip (never first or last). The Phase 5 engine estimates such rows by
distance-proportional interpolation between the nearest timed rows; the parsed
layer never stores a fabricated time.

V11 — the printed ``No.`` column must be 1..N with no gaps and no duplicates
across page continuations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pipeline.parsers.stop_table import ParsedTrain, Stop


@dataclass
class Finding:
    rule: str
    train_no: str | None
    seq: int | None
    detail: str

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "train_no": self.train_no,
            "seq": self.seq,
            "detail": self.detail,
        }


@dataclass
class RuleReport:
    rule: str
    description: str
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    counts_by_train: dict[str, int] = field(default_factory=dict)
    longest_runs: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "description": self.description,
            "checked": self.checked,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "findings": [f.as_dict() for f in self.findings],
            "counts_by_train": dict(sorted(self.counts_by_train.items(), key=lambda kv: -kv[1])),
        }


def _is_timed(stop: Stop) -> bool:
    """A row is timed when it prints at least one clock time."""
    return bool(stop.arrive.value or stop.depart.value)


def _is_untimed(stop: Stop) -> bool:
    """Any row that prints no clock time at all.

    Covers the "Ls + -" pass row and the marker rows (Berh/Sb), which are
    deliberately untimed (ADR 003).
    """
    return stop.arrive.value is None and stop.depart.value is None


def _is_untimed_pass(stop: Stop) -> bool:
    """Backwards-compatible alias used by the gate."""
    return _is_untimed(stop)


def _longest_untimed_run(stops: list[Stop]) -> int:
    best = current = 0
    for stop in stops:
        if _is_untimed(stop):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def validate_v10(trains: list[ParsedTrain]) -> RuleReport:
    """V10: untimed pass rows sit strictly between two timed rows."""
    report = RuleReport(
        "V10",
        "an untimed pass row lies between two timed rows of the same trip",
    )
    runs: dict[str, int] = {}
    for train in trains:
        count = 0
        for index, stop in enumerate(train.stops):
            report.checked += 1
            if not _is_untimed(stop):
                continue
            count += 1
            if index == 0:
                report.findings.append(
                    Finding("V10", train.train_no, stop.seq, "untimed pass row is the first row")
                )
                continue
            if index == len(train.stops) - 1:
                report.findings.append(
                    Finding("V10", train.train_no, stop.seq, "untimed pass row is the last row")
                )
                continue
            before = any(_is_timed(s) for s in train.stops[:index])
            after = any(_is_timed(s) for s in train.stops[index + 1 :])
            if not before:
                report.findings.append(
                    Finding("V10", train.train_no, stop.seq, "no timed row before it in this trip")
                )
            if not after:
                report.findings.append(
                    Finding("V10", train.train_no, stop.seq, "no timed row after it in this trip")
                )
        if count:
            report.counts_by_train[train.train_no or "?"] = count
            runs[train.train_no or "?"] = _longest_untimed_run(train.stops)
    report.longest_runs = runs
    return report


def validate_v11(trains: list[ParsedTrain]) -> RuleReport:
    """V11: the printed No. column is 1..N, no gaps, no duplicates."""
    report = RuleReport(
        "V11",
        "printed No. column is 1..N across page continuations (no gaps, no duplicates)",
    )
    for train in trains:
        if not train.stops:
            report.findings.append(
                Finding("V11", train.train_no, None, "train has no parsed stops")
            )
            continue
        seqs = [stop.seq for stop in train.stops if stop.seq is not None]
        report.checked += len(seqs)

        duplicates = [seq for seq, n in Counter(seqs).items() if n > 1]
        for seq in sorted(duplicates):
            report.findings.append(
                Finding(
                    "V11",
                    train.train_no,
                    seq,
                    f"duplicate sequence number {seq} ({Counter(seqs)[seq]} times)",
                )
            )

        expected = list(range(1, len(seqs) + 1))
        if seqs != expected:
            # Report each gap explicitly so a reviewer can jump to the page.
            present = set(seqs)
            for missing in range(1, max(seqs) + 1):
                if missing not in present:
                    report.findings.append(
                        Finding("V11", train.train_no, missing, f"sequence {missing} missing")
                    )
            if seqs and seqs[0] != 1:
                report.findings.append(
                    Finding("V11", train.train_no, seqs[0], "sequence does not start at 1")
                )
            if seqs != sorted(seqs):
                report.findings.append(
                    Finding("V11", train.train_no, None, "sequence numbers are out of order")
                )
    return report
