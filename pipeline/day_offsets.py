"""Arrive/depart day offsets for a stop that straddles midnight (Q3).

A Gapeka row prints ``Datang`` and ``Berangkat`` separately, so a train can
arrive at 23:58 and depart at 00:03. One ``day_offset`` per row cannot represent
that: whichever value you pick, one of the two times is a day wrong.

The data correction keeps a separate offset for each side:

- ``depart_day_offset`` is the old ``day_offset`` (the row's own day);
- ``arrive_day_offset`` equals it, EXCEPT when ``arrive > depart`` on the clock,
  where the arrival necessarily happened on the previous day.

Provenance: a row where the two differ is ``day_offset_source =
"derived_midnight_dwell"``. Nothing else is inferred.

Usage:
    python -m pipeline.day_offsets
"""

from __future__ import annotations

LONG_DWELL_MINUTES = 60


def _seconds(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def derive(arrive: str | None, depart: str | None, day_offset: int) -> tuple[int, int]:
    """Return ``(arrive_day_offset, depart_day_offset)`` for one printed row."""
    offset = int(day_offset or 0)
    arrive_s = _seconds(arrive)
    depart_s = _seconds(depart)

    if arrive_s is None and depart_s is None:
        return offset, offset
    if arrive_s is None or depart_s is None:
        # A pass row prints one time and has no dwell; both sides share the day.
        return offset, offset
    if arrive_s > depart_s:
        return offset - 1, offset
    return offset, offset


def absolute_times(
    arrive: str | None, depart: str | None, day_offset: int
) -> tuple[int | None, int | None]:
    """Absolute seconds from the service-date midnight, for each printed side."""
    arrive_s = _seconds(arrive)
    depart_s = _seconds(depart)
    arrive_offset, depart_offset = derive(arrive, depart, day_offset)
    arrive_abs = None if arrive_s is None else arrive_s + 86400 * arrive_offset
    depart_abs = None if depart_s is None else depart_s + 86400 * depart_offset
    return arrive_abs, depart_abs


def dwell_minutes(arrive: str | None, depart: str | None, day_offset: int) -> int | None:
    """Dwell in minutes, honouring the midnight correction."""
    arrive_s = _seconds(arrive)
    depart_s = _seconds(depart)
    if arrive_s is None or depart_s is None:
        return None
    arrive_offset, depart_offset = derive(arrive, depart, day_offset)
    total = (depart_s + 86400 * depart_offset) - (arrive_s + 86400 * arrive_offset)
    return int(total // 60)


def is_long_dwell(minutes: int | None) -> bool:
    return minutes is not None and minutes > LONG_DWELL_MINUTES


def source(arrive: str | None, depart: str | None, day_offset: int) -> str:
    arrive_offset, depart_offset = derive(arrive, depart, day_offset)
    if arrive_offset != depart_offset:
        return "derived_midnight_dwell"
    return "printed"


def main() -> int:
    import json
    import sqlite3
    from collections import Counter
    from pathlib import Path

    db = Path("data/gapeka.db")
    if not db.exists():
        print("build the database first")
        return 2

    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT trip_id, seq, station_code, arrive, depart, day_offset, stop_type"
            " FROM stop_times ORDER BY trip_id, seq"
        ).fetchall()
    finally:
        connection.close()

    affected = []
    dwell_hist: Counter[str] = Counter()
    for trip_id, seq, code, arrive, depart, day_offset, stop_type in rows:
        arrive_offset, depart_offset = derive(arrive, depart, day_offset)
        minutes = dwell_minutes(arrive, depart, day_offset)
        if minutes is not None:
            if minutes <= 5:
                dwell_hist["0-5"] += 1
            elif minutes <= 15:
                dwell_hist["6-15"] += 1
            elif minutes <= 30:
                dwell_hist["16-30"] += 1
            elif minutes <= 60:
                dwell_hist["31-60"] += 1
            else:
                dwell_hist[">60"] += 1
        if arrive_offset != depart_offset:
            affected.append(
                {
                    "trip_id": trip_id,
                    "seq": seq,
                    "station_code": code,
                    "arrive": arrive,
                    "depart": depart,
                    "day_offset": day_offset,
                    "arrive_day_offset": arrive_offset,
                    "depart_day_offset": depart_offset,
                    "dwell_minutes": minutes,
                    "long_dwell": is_long_dwell(minutes),
                    "stop_type": stop_type,
                }
            )

    payload = {
        "note": (
            "Rows where the arrival and the departure are on different days. "
            "arrive_day_offset is day_offset-1 exactly when the clock goes "
            "backwards (arrive > depart)."
        ),
        "affected_count": len(affected),
        "affected": affected,
        "dwell_distribution_minutes": dict(sorted(dwell_hist.items())),
        "long_dwell_threshold_minutes": LONG_DWELL_MINUTES,
        "long_dwells": [row for row in affected if row["long_dwell"]],
    }
    Path("data/review/day_offset_correction.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"affected rows: {len(affected)}")
    for row in affected:
        print(
            f"  {row['trip_id']} seq {row['seq']} {row['station_code']}: "
            f"{row['arrive']} ({row['arrive_day_offset']}) -> "
            f"{row['depart']} ({row['depart_day_offset']}), dwell {row['dwell_minutes']} min"
        )
    print(f"dwell distribution: {payload['dwell_distribution_minutes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
