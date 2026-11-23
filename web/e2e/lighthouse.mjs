// T7: Lighthouse (mobile) against the built site. Report only: the numbers go to
// data/review/lighthouse.json and are quoted from there, never recomputed.
//
// Tiles are BLOCKED so the score measures the app shell and the schedule data,
// not the tile provider's latency. A `page.route` stub does NOT work here:
// Lighthouse opens its own tab in the browser, so a route registered on a page we
// created never applies. Without blocking, the run fetched 6 real OSM tiles
// (141,926 bytes) over a throttled 1.6 Mbit link and TBT measured tile download,
// not application work.

import { chromium } from "playwright";
import lighthouse from "lighthouse";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REVIEW = resolve(HERE, "../../data/review");
const URL_UNDER_TEST = process.env.LH_URL ?? "http://127.0.0.1:4173/";
// Set LH_BLOCK=0 to measure WITH the real tile network, which is what the old
// harness accidentally did. Kept switchable so both numbers stay reproducible.
const BLOCK_TILES = process.env.LH_BLOCK !== "0";
const OUT_NAME = BLOCK_TILES ? "lighthouse.json" : "lighthouse_unblocked.json";

mkdirSync(REVIEW, { recursive: true });

const browser = await chromium.launch({
  args: ["--remote-debugging-port=9222", "--no-sandbox"],
});
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();
await page.route("**/tile.openstreetmap.org/**", (route) =>
  route.fulfill({
    status: 200,
    contentType: "image/png",
    body: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    ),
  }),
);

const endpoint = `http://127.0.0.1:9222`;
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
    // Lighthouse uses its own target, so blocking must be a setting, not a route.
    ...(BLOCK_TILES ? { blockedUrlPatterns: ["*tile.openstreetmap.org*"] } : {}),
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
  note:
    (BLOCK_TILES
      ? "Report only. Tile requests are blocked, so these numbers describe the app, "
        + "not the tile provider. Blocking logs console errors from the failed tile "
        + "fetches, which is the only reason best-practices reads below 100 here; take "
        + "best-practices from an unblocked run."
      : "Report only. Tiles are NOT blocked: this measures the app PLUS the real "
        + "tile network over mobile throttling, which is what the old harness did."),
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
