// Lighthouse (mobile) against the built FRONTEND bundle — report only.
//
// The numbers land in `data/review/frontend_lighthouse.json` and are quoted from
// there, never recomputed. `make frontend-lighthouse` builds `dist-e2e` and
// serves it on port 4174, so this file only has to drive Lighthouse.
//
// External tile hosts are BLOCKED, on purpose:
//   * `tiles.openfreemap.org` (basemap, positron/liberty)
//   * `tiles.openrailwaymap.org` (optional overlay)
// A throttled mobile run would otherwise measure the tile provider's latency, not
// the app. A `page.route` stub cannot do this: Lighthouse opens its own tab, so a
// route registered on a page we created never applies — blocking must be a
// Lighthouse setting (`blockedUrlPatterns`). The cost is console errors from the
// aborted fetches, which is why `best-practices` is read with that caveat in mind.

import { chromium } from "@playwright/test";
import lighthouse from "lighthouse";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REVIEW = resolve(HERE, "../../data/review");
const URL_UNDER_TEST = process.env.LH_URL ?? "http://127.0.0.1:4174/";
const BLOCK_TILES = process.env.LH_BLOCK !== "0";
const OUT_NAME = BLOCK_TILES ? "frontend_lighthouse.json" : "frontend_lighthouse_unblocked.json";

mkdirSync(REVIEW, { recursive: true });

const browser = await chromium.launch({
  args: ["--remote-debugging-port=9222", "--no-sandbox"],
});
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();

const endpoint = "http://127.0.0.1:9222";
const result = await lighthouse(
  URL_UNDER_TEST,
  {
    port: 9222,
    output: "json",
    logLevel: "error",
    onlyCategories: ["performance", "accessibility", "best-practices", "seo"],
    formFactor: "mobile",
    screenEmulation: { mobile: true, width: 390, height: 844, deviceScaleFactor: 3, disabled: false },
    throttling: { rttMs: 150, throughputKbps: 1638.4, cpuSlowdownMultiplier: 4 },
    ...(BLOCK_TILES
      ? {
          blockedUrlPatterns: [
            "*tiles.openfreemap.org*",
            "*tiles.openrailwaymap.org*",
            "*tile.openstreetmap.org*",
          ],
        }
      : {}),
  },
  undefined,
);

await browser.close();
await page.close().catch(() => {});

const categories = result?.lhr?.categories ?? {};
const audits = result?.lhr?.audits ?? {};

const summary = {
  url: URL_UNDER_TEST,
  form_factor: "mobile",
  viewport: "390x844",
  note: BLOCK_TILES
    ? "Report only. External tile hosts (OpenFreeMap basemap, OpenRailwayMap overlay) are "
      + "blocked, so these numbers describe the app shell and the schedule payload, not the "
      + "tile provider. Blocking logs console errors from the aborted tile fetches; read "
      + "best-practices with that in mind."
    : "Report only. Tiles are NOT blocked: this measures the app plus the real tile network "
      + "over mobile throttling.",
  tiles_blocked: BLOCK_TILES,
  scores: Object.fromEntries(
    Object.entries(categories).map(([key, value]) => [
      key,
      value && typeof value === "object" && "score" in value ? Math.round((value.score ?? 0) * 100) : null,
    ]),
  ),
  metrics: {
    first_contentful_paint_ms: audits["first-contentful-paint"]?.numericValue ?? null,
    largest_contentful_paint_ms: audits["largest-contentful-paint"]?.numericValue ?? null,
    total_blocking_time_ms: audits["total-blocking-time"]?.numericValue ?? null,
    cumulative_layout_shift: audits["cumulative-layout-shift"]?.numericValue ?? null,
    speed_index_ms: audits["speed-index"]?.numericValue ?? null,
    total_byte_weight: audits["total-byte-weight"]?.numericValue ?? null,
  },
  endpoint,
};

writeFileSync(resolve(REVIEW, OUT_NAME), JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 2));
