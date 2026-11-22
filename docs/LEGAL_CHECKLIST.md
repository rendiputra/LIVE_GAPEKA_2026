# Legal checklist — decide before public release

Nothing here is resolved by this repository. Each item needs a conscious decision
from the human owner, recorded with a date.

| # | Item | Why it matters | Status |
|---|---|---|---|
| 1 | **Right to use and display the Gapeka data** | The timetable comes from a KAI publication. Publishing derived positions and schedules may need permission or a licence, even though the document was publicly distributed. | OPEN |
| 2 | **OSM ODbL and the derived geometries** | Route polylines are derived from OpenStreetMap. ODbL is share-alike for *derivative databases*, not for "produced works" like a map image, but publishing the derived geometry as JSON is closer to a derivative database. Attribution `© OpenStreetMap contributors` is mandatory either way. | OPEN |
| 3 | **Tile provider terms** | Public OSM tiles are not allowed for this traffic. Whichever provider is chosen, its terms govern caching, attribution and rate limits. | OPEN |
| 4 | **No tracking / analytics by default** | The app ships no analytics, no cookies, no third-party scripts. If analytics is added later it needs a consent decision. | DECIDED: none shipped |
| 5 | **Station coordinates from Wikidata (CC0)** | CC0 needs no attribution, but the provenance is recorded per station anyway. | RECORDED |
| 6 | **Disclaimer wording** | The UI must always say the positions are estimates, not actual. Wording is fixed in the manifest and rendered on every page. | DECIDED |
| 7 | **Trademark / branding** | "Kereta Api Indonesia", "KAI" and train names may be trademarks. Avoid implying endorsement. | OPEN |
| 8 | **Pre-release banner** | Before 2026-12-01 the UI shows a preview banner; this is a factual statement, not a licence issue. | DECIDED |

## What must be true before launch

- Item 1 and item 3 have a written decision with a date.
- Item 2 has a decision about whether to publish the derived geometry as a data
  file, or only to render it.
- The attribution string `© OpenStreetMap contributors` is visible on every page
  that shows a map.
- The disclaimer text matches the manifest, so it cannot drift from the data.
