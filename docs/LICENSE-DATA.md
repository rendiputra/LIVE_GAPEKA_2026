# Data licensing — DRAFT FOR HUMAN REVIEW

> **Status: draft.** This file records the intended position on the two
> OSM-derived files. It is **not** a legal opinion and it is **not** in force.
> A human must review and decide every item before public release.

## What the site publishes

Three kinds of data are published, and they have different origins:

| File | Origin | Proposed licence |
|---|---|---|
| `trips.json`, `manifest.json` | Parsed from the Gapeka 2026 timetable PDF | **Undecided** — see `docs/LEGAL_CHECKLIST.md` item 1 |
| `segments.json` (route polylines) | Derived from OpenStreetMap rail ways, via a Geofabrik extract | **ODbL 1.0** (share-alike) |
| `stations.json` (coordinates) | Wikidata (CC0) and OpenStreetMap station nodes, with human overrides | **ODbL 1.0** for the OSM-derived rows; CC0 rows carry no restriction |

## Why the two OSM files are separated

Providing the schedule and the OSM-derived geometry in the **same** file would
make it hard to argue which licence covers which part. Keeping them apart makes
the boundary visible:

- `trips.json` refers to segments by **numeric id**, not by geometry.
- A consumer of the schedule alone never receives OSM-derived coordinates.
- The geometry files carry their own attribution and licence statement.

## Proposed ODbL position (submit, not cite)

ODbL distinguishes a **Derivative Database** (share-alike) from a **Produced Work**
(no share-alike). Our position:

- The published `segments.json` is a *Derivative Database*: it is an extraction and
  re-projection of OSM way geometry.
- Therefore it is offered under ODbL 1.0, with attribution
  "© OpenStreetMap contributors" and a link to
  <https://www.openstreetmap.org/copyright>.
- The rendered map is a *Produced Work*; no share-alike applies to the map image.
- Any "substantial" extraction from our `segments.json` must keep ODbL.

## Required attribution (every page)

- Map: "© OpenStreetMap contributors", visible, linking to the copyright page.
- The About dialog repeats it and states that the basemap is a self-hosted
  Protomaps build derived from OSM.

## What is NOT decided here

1. Whether we have the right to publish the schedule at all.
2. Whether the Gapeka PDF's ministerial-decree pages impose a credit requirement
   or a restriction.
3. Whether "substantial extraction" applies to a public JSON file of 391
   polylines.

Each of those needs a human decision, recorded with a date, in
`docs/LEGAL_CHECKLIST.md`.
