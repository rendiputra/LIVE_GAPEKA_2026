/**
 * Fix 3: the 391 Gapeka rail segments must be present on the FIRST paint.
 *
 * The bug was a startup race: the map style loads before the 1.1 MB schedule
 * payload arrives, so the rail source was created empty and never refilled.
 * Rails only appeared after an overlay toggle forced a style rebuild.
 *
 * A canvas pixel probe cannot see this: MapLibre renders without
 * `preserveDrawingBuffer`, so `readPixels` outside a frame returns garbage
 * (it reported 0 rail pixels even while rails were clearly visible on screen).
 * The app therefore publishes a read-only `data-rail-features` count on the map
 * container, set by the same code path that hands geometry to MapLibre.
 */
import { expect, test } from "@playwright/test";

const RAIL_SEGMENTS = 391;

test("rails reach the map on a cold load without touching the layers menu", async ({ page }) => {
  const mapErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.text().includes("[LiveMap]")) mapErrors.push(msg.text());
  });

  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  const map = page.locator('[data-testid="live-map"]');
  // No interaction at all: the layers menu has never been opened.
  await expect(page.locator('div[role="dialog"][aria-label="Lapisan peta"]')).toHaveCount(0);

  await expect
    .poll(async () => map.getAttribute("data-rail-features"), { timeout: 30_000 })
    .toBe(String(RAIL_SEGMENTS));

  // Regression guard for the original symptom: an overlay round-trip must not
  // change the count (it used to be the only way to make rails appear).
  await page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first().click();
  await page.getByRole("radio", { name: "Infrastruktur" }).filter({ visible: true }).first().click();
  await page.waitForTimeout(1_200);
  await page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first().click();
  await page.getByRole("radio", { name: "Default" }).filter({ visible: true }).first().click();
  await page.waitForTimeout(1_200);

  await expect.poll(async () => map.getAttribute("data-rail-features")).toBe(String(RAIL_SEGMENTS));
  expect(mapErrors, mapErrors.join("\n")).toEqual([]);
});