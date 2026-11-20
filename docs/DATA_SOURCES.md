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

## OpenStreetMap (secondary)

- Endpoint: `https://overpass-api.de/api/interpreter`
- Licence: **ODbL 1.0** — attribution to OpenStreetMap contributors is required
  wherever this data is shown.
- Used for: `railway=station` / `railway=halt` nodes inside Java, matched by
  normalised name when Wikidata has no usable coordinate.
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
