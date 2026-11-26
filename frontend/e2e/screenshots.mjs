// Review screenshots for the Turn 3b report. This is EVIDENCE, not a test — the
// assertions live in `acceptance.spec.ts`, `a11y.spec.ts` and the bug specs.
//
//   pnpm build
//   npx vite preview --outDir dist --port 4173 --strictPort &
//   node e2e/screenshots.mjs
//
// Output: data/review/frontend_screens/
//
// Tiles are deliberately NOT blocked here: a blank basemap would hide exactly
// what the screenshots document (rails over real geography). `animations:
// "disabled"` freezes the pulse/progress animations so two runs match.

import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../../data/review/frontend_screens");
const BASE = process.env.SHOT_URL ?? "http://127.0.0.1:4173/";

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();

async function ready(page) {
  await page.goto(BASE);
  // Two status pills exist (desktop cluster / mobile row); only one is visible.
  await page
    .getByText(/Live \(Estimasi\)/)
    .filter({ visible: true })
    .first()
    .waitFor({ timeout: 40_000 });
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="live-map"]');
      return (
        el?.getAttribute("data-rail-features") === "391" &&
        Number(el?.getAttribute("data-station-features") ?? 0) > 100
      );
    },
    null,
    { timeout: 30_000 },
  );
  // Let the basemap finish its first tile batch.
  await page.waitForTimeout(2_500);
}

/**
 * Pin 09:00 WIB. The screenshots are taken in the evening, when the daytime
 * trains the report refers to (KA 249 among them) have already terminated; a
 * pinned instant shows a populated inspector instead of "Tidak aktif".
 */
async function pinMorning(page) {
  await page.getByRole("slider", { name: /Geser waktu/i }).fill("540");
  await page
    .getByText(/Simulasi \(Estimasi\)/)
    .filter({ visible: true })
    .first()
    .waitFor({ timeout: 15_000 });
  await page.waitForTimeout(800);
}

async function openTrain(page, query) {
  await page.locator("#search").fill(query);
  const results = page.getByRole("dialog", { name: "Hasil pencarian" });
  await results.waitFor({ state: "visible", timeout: 15_000 });
  await results
    .getByRole("region", { name: "Kereta Api" })
    .getByRole("button")
    .first()
    .click();
}

async function shot(page, name) {
  await page.screenshot({ path: resolve(OUT, name), animations: "disabled" });
  console.log("wrote", resolve(OUT, name));
}

const desktop = await browser.newContext({ viewport: { width: 1280, height: 800 } });
{
  const page = await desktop.newPage();
  await ready(page);
  await shot(page, "desktop-01-load.png");

  await pinMorning(page);
  await openTrain(page, "249");
  const inspector = page.getByRole("region", { name: /Inspektori KA 249/i });
  await inspector.waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForTimeout(600);
  await shot(page, "desktop-02-inspector-249.png");

  // Clear the selection before opening the popover.
  await page.locator("body").click({ position: { x: 20, y: 400 } });
  const layers = page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first();
  await layers.click();
  const panel = page.getByRole("dialog", { name: "Lapisan peta" }).filter({ visible: true });
  await panel.waitFor({ state: "visible" });
  await shot(page, "desktop-03-layers.png");

  // OpenRailwayMap Max Speed and its legend; the legend must clear the zoom
  // controls (bottom-right stack).
  await panel.getByRole("radio", { name: /Max Speed/ }).click();
  await page.locator('[data-testid="overlay-legend"]').waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForTimeout(2_000);
  await shot(page, "desktop-04-maxspeed-legend.png");
  await page.close();
}

const mobile = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 2,
});
{
  const page = await mobile.newPage();
  await ready(page);
  await shot(page, "mobile-01-load.png");

  await pinMorning(page);
  await openTrain(page, "249");
  const inspector = page.getByRole("region", { name: /Inspektori KA 249/i });
  await inspector.waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForTimeout(600);
  await shot(page, "mobile-02-inspector-compact.png");

  await inspector.getByRole("button", { expanded: false }).click();
  await inspector.getByRole("button", { expanded: true }).waitFor({ state: "visible" });
  await page.waitForTimeout(600);
  await shot(page, "mobile-03-inspector-expanded.png");

  await inspector.getByRole("button", { name: /Tutup inspektori/i }).click();
  const layers = page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first();
  await layers.click();
  await page
    .getByRole("dialog", { name: "Lapisan peta" })
    .filter({ visible: true })
    .waitFor({ state: "visible" });
  await shot(page, "mobile-04-layers.png");
  await page.close();
}

await browser.close();
