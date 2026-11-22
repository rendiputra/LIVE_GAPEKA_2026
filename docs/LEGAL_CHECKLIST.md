# Legal checklist — decide before public release

Nothing here is resolved by this repository. Each item needs a conscious decision
from the human owner, recorded with a date.

| # | Item | Why it matters | Status |
|---|---|---|---|
| 1 | **Right to use and display the Gapeka data** | The timetable comes from a KAI publication. Publishing derived positions and schedules may need permission or a licence, even though the document was publicly distributed. **Note:** the PDF opens with ministerial-decree pages (PDF 1-5, image-only), so the document may carry a formal decree, not just a timetable. Decide whether to publish, and how to credit KAI / Kemenhub. | OPEN |
| 2 | **OSM ODbL and the derived geometries** | Route polylines are derived from OpenStreetMap. ODbL is share-alike for *derivative databases*, not for "produced works" like a map image. **Position taken (draft):** publish the geometry and the OSM-derived station coordinates as separate files under ODbL 1.0 with attribution, kept apart from the schedule file. Draft: `docs/LICENSE-DATA.md`. Human decides. | DRAFTED — decide |
| 3 | **Tile provider terms** | **Decided:** self-hosted Protomaps PMTiles extract (ADR 009). Tiles must be hosted on object storage with Range support and CORS. Record the final bucket URL. Public OSM tiles are blocked by a build-time failure. | DECIDED (hosting TBD) |
| 4 | **No tracking / analytics by default** | The app ships no analytics, no cookies, no third-party scripts. If analytics is added later it needs a consent decision. | DECIDED: none shipped |
| 5 | **Station coordinates from Wikidata (CC0)** | CC0 needs no attribution, but the provenance is recorded per station anyway. | RECORDED |
| 6 | **Disclaimer wording** | The UI must always say the positions are estimates, not actual. Wording is fixed in the manifest and rendered on every page. | DECIDED |
| 7 | **Trademark / branding** | "Kereta Api Indonesia", "KAI" and train names may be trademarks. Avoid implying endorsement. | OPEN |
| 8 | **Pre-release banner** | Before 2026-12-01 the UI shows a preview banner; this is a factual statement, not a licence issue. | DECIDED |

## What must be true before launch

- Item 1 has a written decision with a date, including how KAI / Kemenhub are
  credited.
- Item 2 is signed off (or the geometry is rendered but not published).
- Item 3's bucket URL is recorded.
- The attribution string `© OpenStreetMap contributors` is visible on every page
  that shows a map.
- The disclaimer text matches the manifest, so it cannot drift from the data.
- `docs/LICENSE-DATA.md` is reviewed and loses its DRAFT banner, or is deleted.
