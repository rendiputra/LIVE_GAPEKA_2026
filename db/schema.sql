-- Gapeka 2026 MVP schema (SQLite).
--
-- Mirrors AGENTS.md section 5, extended for the fields the parsers actually
-- produce. Every timestamp is station-local time plus a time zone; day_offset
-- carries the midnight rollover (Hard Rule 10).
--
-- Load with PRAGMA foreign_keys = ON.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS stop_times;
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS trains;
DROP TABLE IF EXISTS calendar;
DROP TABLE IF EXISTS stations;
DROP TABLE IF EXISTS segments;
DROP TABLE IF EXISTS overrides;
DROP TABLE IF EXISTS gapeka_versions;

CREATE TABLE gapeka_versions (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    effective_from  TEXT    NOT NULL,           -- ISO date, parsed from dividers
    effective_to    TEXT,                       -- null: the PDF states none
    pdf_sha256      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'validated', 'active', 'retired')),
    notes           TEXT
);

CREATE TABLE stations (
    code            TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,           -- exactly as printed in the PDF
    -- Coordinates are external, never inferred. All five fields move together.
    lat             REAL,
    lon             REAL,
    coord_source    TEXT    CHECK (coord_source IN ('wikidata', 'osm')),
    coord_source_id TEXT,
    coord_match     TEXT    CHECK (coord_match IN ('code', 'name', 'name_normalised')),
    coord_confidence TEXT   CHECK (coord_confidence IN ('high', 'medium', 'low')),
    coord_retrieved TEXT,                       -- ISO date
    CHECK (
        (lat IS NULL AND lon IS NULL AND coord_source IS NULL)
        OR (lat IS NOT NULL AND lon IS NOT NULL AND coord_source IS NOT NULL
            AND coord_source_id IS NOT NULL AND coord_match IS NOT NULL
            AND coord_confidence IS NOT NULL AND coord_retrieved IS NOT NULL)
    ),
    CHECK (lat IS NULL OR (lat BETWEEN -90 AND 90)),
    CHECK (lon IS NULL OR (lon BETWEEN -180 AND 180))
);

CREATE TABLE trains (
    train_no        TEXT    PRIMARY KEY,
    name            TEXT,
    class           TEXT,
    relation        TEXT
);

CREATE TABLE trips (
    trip_id             TEXT    PRIMARY KEY,     -- deterministic, see build_db.py
    train_no            TEXT    NOT NULL REFERENCES trains(train_no),
    version_id          INTEGER NOT NULL REFERENCES gapeka_versions(id),
    book                INTEGER NOT NULL CHECK (book IN (1, 2)),
    service_class       TEXT    NOT NULL
                        CHECK (service_class IN ('reguler', 'fakultatif', 'unknown')),
    service_class_source TEXT   NOT NULL,
    completeness        TEXT    NOT NULL
                        CHECK (completeness IN
                               ('complete', 'truncated_at_loaded_pages', 'unknown')),
    has_untimed_markers INTEGER NOT NULL DEFAULT 0 CHECK (has_untimed_markers IN (0, 1)),
    relation            TEXT,
    origin              TEXT    REFERENCES stations(code),
    destination         TEXT    REFERENCES stations(code),
    source_pages        TEXT    NOT NULL,        -- JSON array of PDF page numbers
    needs_review        TEXT    NOT NULL DEFAULT '[]'   -- JSON array
);

CREATE TABLE stop_times (
    trip_id         TEXT    NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL CHECK (seq >= 1),
    station_code    TEXT    NOT NULL REFERENCES stations(code),
    arrive          TEXT,                       -- HH:MM:SS, station-local
    depart          TEXT,
    day_offset      INTEGER NOT NULL DEFAULT 0 CHECK (day_offset IN (0, 1, 2)),
    stop_type       TEXT    NOT NULL
                    CHECK (stop_type IN ('stop', 'pass', 'unknown_untimed')),
    time_source     TEXT    NOT NULL
                    CHECK (time_source IN ('printed', 'not_printed', 'marker', 'empty')),
    raw_arrive      TEXT    NOT NULL DEFAULT '',
    raw_depart      TEXT    NOT NULL DEFAULT '',
    estimated       INTEGER NOT NULL DEFAULT 0 CHECK (estimated IN (0, 1)),
    speed_raw       TEXT    NOT NULL DEFAULT '',
    keterangan_raw  TEXT    NOT NULL DEFAULT '',
    source_page     INTEGER NOT NULL,
    needs_review    TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (trip_id, seq)
);

CREATE TABLE calendar (
    trip_id         TEXT    NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    service_pattern TEXT,                       -- 'daily' only when assumed
    pattern_source  TEXT    NOT NULL
                    CHECK (pattern_source IN
                           ('gapeka_pdf', 'assumed', 'override', 'external', 'unknown')),
    valid_from      TEXT,
    valid_to        TEXT,                       -- null everywhere (ADR 002)
    PRIMARY KEY (trip_id)
);

CREATE TABLE segments (
    from_station    TEXT    NOT NULL REFERENCES stations(code),
    to_station      TEXT    NOT NULL REFERENCES stations(code),
    geometry        TEXT,                       -- reserved for Phase 4
    length_m        REAL,
    geometry_quality TEXT   CHECK (geometry_quality IN ('osm', 'straight_line')),
    PRIMARY KEY (from_station, to_station)
);

CREATE TABLE overrides (
    id              INTEGER PRIMARY KEY,
    target_table    TEXT    NOT NULL,
    target_key      TEXT    NOT NULL,
    patch_json      TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    created_by      TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
);

CREATE INDEX idx_stop_times_station ON stop_times(station_code);
CREATE INDEX idx_stop_times_arrive ON stop_times(arrive);
CREATE INDEX idx_trips_train_no ON trips(train_no);
CREATE INDEX idx_calendar_source ON calendar(pattern_source);
