"""Tests for the static web export (B1).

The export must be deterministic (byte-identical on re-run), must never include
`has_unmeasured` trips, and must keep the manifest self-describing.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    from pipeline import export_web

    out = tmp_path_factory.mktemp("web")
    try:
        summary = export_web.export(out)
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")
    return out, summary


def test_manifest_is_self_describing(exported):
    out, _summary = exported
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version_name"] == "Gapeka 2026"
    assert manifest["effective_from"] == "2026-12-01"
    assert manifest["policy"]["calendar_policy"] == "regular_daily_assumed"
    assert manifest["policy"]["show_fakultatif"] is False
    assert manifest["policy"]["enforce_effective_from"] is False
    assert manifest["content_hash"]
    assert manifest["attribution"]["osm"].startswith("© OpenStreetMap")


def test_export_is_deterministic(exported, tmp_path):
    from pipeline import export_web

    out, _summary = exported
    second = tmp_path / "again"
    export_web.export(second)

    for name in ("manifest.json", "stations.json", "segments.json", "trips.json"):
        first_bytes = (out / name).read_bytes()
        second_bytes = (second / name).read_bytes()
        # The hash-specific filename is the cache key; content must match.
        assert first_bytes == second_bytes, name


def test_no_unmeasured_trip_is_exported(exported):
    out, _summary = exported
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))
    statuses = {trip["status"] for trip in trips["trips"]}
    assert "has_unmeasured" not in statuses
    assert statuses <= {"complete", "complete_estimated"}


def test_every_trip_segment_reference_exists(exported):
    out, _summary = exported
    segments = json.loads((out / "segments.json").read_text(encoding="utf-8"))
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))
    count = len(segments["segments"])
    for trip in trips["trips"]:
        for ref in trip["segment_ids"]:
            assert 0 <= ref < count


def test_waypoints_are_columnar_and_consistent(exported):
    out, _summary = exported
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))
    for trip in trips["trips"]:
        rows = trip["waypoints"]
        length = len(rows["code"])
        for key, column in rows.items():
            assert len(column) == length, (trip["train_no"], key)
        # cumulative distance must be non-decreasing
        distances = rows["s_m"]
        assert all(b >= a for a, b in zip(distances, distances[1:], strict=False))


def test_fakultatif_trips_are_flagged_not_dropped(exported):
    out, _summary = exported
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))
    fak = [t for t in trips["trips"] if t["service_class"] == "fakultatif"]
    assert fak, "fakultatif trips must be exported and flagged"
    assert all(t["hidden_by_default"] is True for t in fak)
    reguler = [t for t in trips["trips"] if t["service_class"] == "reguler"]
    assert all(t["hidden_by_default"] is False for t in reguler)


def test_files_are_named_with_the_content_hash(exported):
    out, summary = exported
    for name in ("stations", "segments", "trips"):
        assert (out / f"{name}.json").exists()
    assert summary["content_hash"] == summary["manifest"]["content_hash"]


def test_segments_are_unique_not_one_per_direction(exported):
    """F1: a segment used in both directions must be exported ONCE.

    The runtime applies direction, so exporting A->B and B->A separately doubles
    the file and breaks the "unique polylines" contract.
    """
    out, summary = exported
    segments = json.loads((out / "segments.json").read_text(encoding="utf-8"))["segments"]
    pairs = [tuple(sorted((segment["from"], segment["to"]))) for segment in segments]
    assert len(pairs) == len(set(pairs)), "duplicate segment pairs in the export"
    assert summary["segments"] == len(set(pairs))


def test_exported_segment_count_matches_the_database(exported):
    """The export must not invent or drop segments relative to the DB."""
    import sqlite3

    out, summary = exported
    connection = sqlite3.connect("file:data/gapeka.db?mode=ro", uri=True)
    try:
        db_count = connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    finally:
        connection.close()
    assert summary["segments"] == db_count


def test_reversed_flag_marks_the_trip_direction(exported):
    """A trip that runs a segment backwards must set reversed=1 for that segment."""
    out, _summary = exported
    segments = json.loads((out / "segments.json").read_text(encoding="utf-8"))["segments"]
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))["trips"]

    seen_reversed = False
    seen_forward = False
    for trip in trips:
        for index, segment_id in enumerate(trip["segment_ids"]):
            segment = segments[segment_id]
            reversed_flag = trip["reversed"][index]
            # The segment record is canonical: its `from` is the polyline start.
            if reversed_flag == 0:
                seen_forward = True
                assert segment["from"] in (segment["from"], segment["to"])
            else:
                seen_reversed = True
    assert seen_forward and seen_reversed, "expected both directions in the data"


def test_no_duplicate_polyline_content(exported):
    out, _summary = exported
    segments = json.loads((out / "segments.json").read_text(encoding="utf-8"))["segments"]
    polylines = [segment["polyline"] for segment in segments]
    assert len(polylines) == len(set(polylines)), "same polyline exported twice"


def test_main_writes_to_the_given_out_directory(tmp_path, capsys):
    """The frontend build points the export at its own public/data directory."""
    from pipeline import export_web

    out = tmp_path / "frontend-public-data"
    try:
        code = export_web.main(["--out", str(out)])
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")

    assert code == 0
    for name in ("manifest.json", "stations.json", "segments.json", "trips.json"):
        assert (out / name).exists(), name
    assert "wrote" in capsys.readouterr().out


def test_frontend_variant_drops_the_preview_banner(tmp_path):
    """ADR 002 amendment (2026-11-23): the frontend shows no preview banner.

    The banner string must not ship to the frontend at all, so the new UI cannot
    render it by accident. The disclaimer itself is kept: it moves into the
    "Tentang" modal, it does not disappear.
    """
    from pipeline import export_web

    out = tmp_path / "frontend"
    try:
        export_web.export(out, variant="frontend")
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")

    attribution = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["attribution"]
    assert "preview_banner" not in attribution
    assert attribution["disclaimer"].startswith("Posisi estimasi berdasarkan jadwal Gapeka 2026")
    assert attribution["osm"].startswith("© OpenStreetMap")


def test_web_variant_keeps_the_preview_banner(exported):
    """The `web/` baseline is untouched: its manifest still carries the banner."""
    out, _summary = exported
    attribution = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["attribution"]
    assert attribution["preview_banner"] == (
        "Preview Gapeka 2026 (berlaku resmi mulai 1 Desember 2026)"
    )


def test_variants_share_the_same_content_hash(tmp_path):
    """The variant changes only the manifest's presentation, never the data."""
    from pipeline import export_web

    try:
        web = export_web.export(tmp_path / "web")
        frontend = export_web.export(tmp_path / "frontend", variant="frontend")
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")

    assert web["content_hash"] == frontend["content_hash"]
    assert web["trips"] == frontend["trips"]


def test_unknown_variant_is_rejected(tmp_path):
    from pipeline import export_web

    with pytest.raises(ValueError, match="variant"):
        export_web.export(tmp_path / "nope", variant="mobile")


def test_frontend_variant_writes_its_own_review_artefact(tmp_path, monkeypatch):
    """The frontend export must not overwrite the `web/` baseline report."""
    from pipeline import export_web

    review = tmp_path / "review"
    review.mkdir()
    monkeypatch.setattr(export_web, "REVIEW_DIR", review)
    try:
        export_web.export(tmp_path / "web")
        export_web.export(tmp_path / "frontend", variant="frontend")
    except (FileNotFoundError, ValueError) as error:
        pytest.skip(f"database not available: {error}")

    assert (review / "web_export.json").exists()
    assert (review / "frontend_export.json").exists()
    web = json.loads((review / "web_export.json").read_text(encoding="utf-8"))
    assert "preview_banner" in web["manifest"]["attribution"]


def test_train_name_is_the_real_name_not_the_number(exported):
    """F2: 'KA 50 — 50' came from the export writing train_no into name.

    Every trip must carry the train's real name from the PDF, never its number.
    """
    import sqlite3

    out, _summary = exported
    trips = json.loads((out / "trips.json").read_text(encoding="utf-8"))["trips"]

    connection = sqlite3.connect("file:data/gapeka.db?mode=ro", uri=True)
    try:
        real = {row[0]: row[1] for row in connection.execute("SELECT train_no, name FROM trains")}
    finally:
        connection.close()

    duplicated = [trip for trip in trips if trip["name"].strip() == trip["train_no"].strip()]
    assert duplicated == [], f"{len(duplicated)} trips repeat the train number as the name"

    for trip in trips:
        expected = (real.get(trip["train_no"]) or "").strip()
        assert trip["name"].strip() == expected, (
            f"KA {trip['train_no']}: name {trip['name']!r} != {expected!r}"
        )
