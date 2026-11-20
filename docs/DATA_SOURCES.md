# External data sources

All coordinates come from external sources. None are derived from the PDF, and
none are guessed or interpolated.

## Wikidata (primary)

- Endpoint: `https://query.wikidata.org/sparql`
- Licence: **CC0** (public domain dedication)
- Used for: station code (P296) and coordinates (P625) of Indonesian railway
  stations.
- Match method: **by station code first**, then normalised label.
- Cached payload: `data/external/wikidata_stations.json` (gitignored), with
  source, URL, licence and retrieval date in `data/external/manifest.json`.

## Geofabrik Java extract (rail geometry + station cross-check)

- Endpoint: `https://download.geofabrik.de/asia/indonesia/java/`
- Snapshot used: `java-261119.osm.pbf` (858 MB)
- SHA-256: `79b8f0630867b7ef7f61eddd11b06cffb1ecbce8f32b4d9454490dafb0963f95`
- Licence: **ODbL 1.0** — attribution "© OpenStreetMap contributors" is required.
- Used for: the Phase 4 routing graph (`railway=rail` ways) **and** the independent
  station cross-check (every `railway=station|halt` node).
- Why an extract and not Overpass: Overpass returned HTTP 502/504 repeatedly
  during this run. A hash-pinned Geofabrik snapshot is reproducible.
- Derived cache: `data/external/java_rail_graph.json` (gitignored). The PBF itself
  is **not** committed; only its SHA-256 and retrieval date appear in the manifest.

### Memory note

`pyosmium` with `locations=True` builds a coordinate index for *every* node in
Java (tens of GB). The extractor therefore runs two streaming passes with
`locations=False`: ways first, then nodes filtered to the ~52k IDs the ways use.
Peak memory is a few hundred MB, not tens of GB.

## OpenStreetMap via Overpass (station cross-check only)

- Endpoint: `https://overpass-api.de/api/interpreter`
- Licence: **ODbL 1.0** — attribution to OpenStreetMap contributors is required
  wherever this data is shown.
- Used for: a secondary station cross-check only. The Overpass cache proved too
  thin (499 nodes for all of Java) to serve as a real cross-check, so the
  Geofabrik station list above is preferred. Retained for the manifest record.
- Cached payload: `data/external/osm_stations.json` (gitignored), recorded in the
  same manifest.

## Rules applied

1. A candidate outside the Java bounding box is **rejected**, not matched. Station
   codes collide across islands (Wikidata `TLM` is a Sumatra station while the
   Gapeka's `TLM` is "Telaga Murni" in Java).
2. Two distinct codes resolving to the *same* coordinate are flagged as
   suspicious: at least one external item is wrong.
3. More than one candidate for a code or name goes to
   `data/review/stations_ambiguous.json`; nothing is picked automatically.
4. A coordinate more than 40 km from both of a station's most common route
   neighbours is flagged in `data/review/stations_suspicious_coords.json`.
5. Unmatched codes go to `data/review/stations_unmatched.json` and keep
   `lat`/`lon` NULL. Their segments simply cannot be measured yet.

## Known external-data defects found

| Codes | Problem |
|---|---|
| `LR`, `SD` | Wikidata Q12516294 "Larangan (Tegal)" and Q12516348 "Suradadi" share one coordinate in Madura (~111 km from Tegal). |
| `PS`, `RO` | Two codes on one coordinate near Malang. |
| `PRI`, `TIS` | Two codes on one coordinate; `TIS` is also 52–67 km from both neighbours. |

These are reported, not corrected: inventing a "better" coordinate would violate
Hard Rule 1.
