"""T1: import the human verification result.

Reads ``verification_result.json`` (downloaded from the sheet) and:

- appends a record to ``data/review/verifications.json``;
- writes ``data/review/verification_findings.json`` for any wrong row, with the
  parsed value and the human's note — **nothing is fixed**;
- promotes fully-matching trips to ``tests/golden/`` fixtures with
  ``verified_by_human: true``.

A trip is promoted only when its verdict is ``all_rows_match``. A trip with any
wrong row is NOT promoted, even if the human corrected nothing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date as date_type
from pathlib import Path

DB = Path("data/gapeka.db")
REVIEW = Path("data/review")
VERIFICATIONS = REVIEW / "verifications.json"
FINDINGS = REVIEW / "verification_findings.json"
GOLDEN = Path("tests/golden")


def _stop_rows(trip_id: str) -> list[dict]:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT seq, station_code, arrive, depart, day_offset, stop_type,"
            " raw_arrive, raw_depart, keterangan_raw, speed_raw, source_page"
            " FROM stop_times WHERE trip_id = ? ORDER BY seq",
            (trip_id,),
        ).fetchall()
        names = {
            row[0]: (row[1], row[2])
            for row in connection.execute("SELECT code, name, official_name FROM stations")
        }
    finally:
        connection.close()

    out = []
    for row in rows:
        code = row[1]
        name = names.get(code, (code, None))
        out.append(
            {
                "seq": row[0],
                "station_code": code,
                "station_name": name[0],
                "arrive": row[2],
                "depart": row[3],
                "day_offset": row[4],
                "stop_type": row[5],
                "raw_arrive": row[6],
                "raw_depart": row[7],
                "keterangan_raw": row[8],
                "speed_raw": row[9],
                "source_page": row[10],
            }
        )
    return out


def import_result(result_path: Path, *, dry_run: bool = False) -> dict:
    """Ingest one verification result file. Returns a summary."""
    if not result_path.exists():
        raise FileNotFoundError(result_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))

    trains = payload.get("trains", [])
    if not trains:
        raise ValueError("result has no trains")

    verified_on = payload.get("date") or date_type.today().isoformat()
    promoted = []
    findings = []

    for train in trains:
        trip_id = train["trip_id"]
        wrong = train.get("wrong_rows") or []
        if train.get("verdict") == "all_rows_match" and not wrong:
            promoted.append(
                {
                    "trip_id": trip_id,
                    "train_no": train["train_no"],
                    "book": train["book"],
                    "pages": train.get("pages", []),
                }
            )
            continue

        stops = {row["seq"]: row for row in _stop_rows(trip_id)}
        for row in wrong:
            seq = row.get("seq")
            parsed = stops.get(seq, {})
            findings.append(
                {
                    "trip_id": trip_id,
                    "train_no": train["train_no"],
                    "book": train["book"],
                    "seq": seq,
                    "station_code": parsed.get("station_code"),
                    "page": parsed.get("source_page"),
                    "parsed": {
                        "arrive": parsed.get("arrive"),
                        "depart": parsed.get("depart"),
                        "raw_arrive": parsed.get("raw_arrive"),
                        "raw_depart": parsed.get("raw_depart"),
                        "speed_raw": parsed.get("speed_raw"),
                        "day_offset": parsed.get("day_offset"),
                        "stop_type": parsed.get("stop_type"),
                    },
                    "note": row.get("note", ""),
                    "status": "open",
                    "reported_by": "human",
                    "reported_on": verified_on,
                }
            )

    # --- golden fixtures ---------------------------------------------------
    fixtures = []
    if promoted and not dry_run:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for entry in promoted:
            fixture = {
                "verified_by_human": True,
                "verifier": payload.get("verifier", "human"),
                "date": verified_on,
                "method": payload.get(
                    "method",
                    "visual comparison of PDF page images against the parsed table",
                ),
                "scope": {
                    "note": (
                        "All rows of this trip were compared against the PDF page "
                        "images in data/review/verification_sheet.html."
                    ),
                    "pages": entry["pages"],
                },
                "trains": [
                    {
                        "train_no": entry["train_no"],
                        "book": entry["book"],
                        "trip_id": entry["trip_id"],
                        "stops": _stop_rows(entry["trip_id"]),
                    }
                ],
            }
            path = GOLDEN / f"verified_{entry['train_no'].replace(' ', '')}.json"
            path.write_text(
                json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            fixtures.append(str(path))

    # --- verifications.json ------------------------------------------------
    if not dry_run:
        records = (
            json.loads(VERIFICATIONS.read_text(encoding="utf-8"))
            if VERIFICATIONS.exists()
            else {"records": []}
        )
        records.setdefault("records", []).append(
            {
                "verifier": payload.get("verifier", "human"),
                "date": verified_on,
                "method": payload.get(
                    "method",
                    "visual comparison of PDF page images against the parsed table",
                ),
                "scope": {
                    "trains": [entry["train_no"] for entry in promoted],
                    "trips": [entry["trip_id"] for entry in promoted],
                    "trains_with_errors": [f["train_no"] for f in findings],
                    "note": (
                        f"{len(promoted)} train(s) matched every row and were promoted; "
                        f"{len({f['trip_id'] for f in findings})} train(s) had wrong rows "
                        "and were NOT promoted."
                    ),
                },
                "artefact": "data/review/verification_sheet.html",
                "result": "accepted" if not findings else "accepted_with_findings",
            }
        )
        VERIFICATIONS.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        existing = (
            json.loads(FINDINGS.read_text(encoding="utf-8"))
            if FINDINGS.exists()
            else {"findings": []}
        )
        existing.setdefault("findings", []).extend(findings)
        existing["note"] = (
            "Wrong rows reported by a human. Nothing here is fixed automatically; "
            "each entry names the page, the parsed value and the note."
        )
        FINDINGS.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return {
        "verified_on": verified_on,
        "promoted": promoted,
        "findings": findings,
        "fixtures": fixtures,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Import a verification result.")
    parser.add_argument(
        "result",
        type=Path,
        nargs="?",
        default=Path.home() / "Downloads" / "verification_result.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = import_result(args.result, dry_run=args.dry_run)
    print(f"verified on {summary['verified_on']}")
    print(f"  promoted {len(summary['promoted'])} train(s)")
    print(f"  findings {len(summary['findings'])} row(s)")
    for path in summary["fixtures"]:
        print(f"  fixture {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
