/**
 * Fix 6: on a phone the inspector and station board are anchored to the BOTTOM,
 * above the time-travel dock, so the map and the selected train stay visible.
 *
 * Desktop must keep its top-left placement; these assertions are mobile-only
 * because the wrapper switches at the `sm`/`lg` breakpoints.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

const MOBILE = { width: 390, height: 844 } as const;
const DOCK_GAP = 8;

test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
  // Wait for the schedule so search has results.
  await expect
    .poll(async () => page.locator('[data-testid="live-map"]').getAttribute("data-rail-features"))
    .toBe("391");
}

async function openTrain(page: Page, query = "98"): Promise<void> {
  await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill(query);
  const hit = page
    .locator('div[role="dialog"][aria-label="Hasil pencarian"] ul li button')
    .filter({ visible: true })
    .first();
  await expect(hit).toBeVisible({ timeout: 15_000 });
  await hit.click();
  await expect(page.locator('section[aria-label^="Inspektori"]')).toBeVisible({
    timeout: 15_000,
  });
}

async function isOccluded(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!top) return true;
    return !(top === element || element.contains(top));
  });
}

test("compact inspector sits in the lower half, clear of the dock", async ({ page }) => {
  await ready(page);
  await openTrain(page);

  const card = page.locator('section[aria-label^="Inspektori"]');
  const dock = page.locator('[aria-label="Kontrol waktu"]');

  const cardBox = await card.boundingBox();
  const dockBox = await dock.boundingBox();
  expect(cardBox).not.toBeNull();
  expect(dockBox).not.toBeNull();

  // The bug: the card floated at the top (y ~136) over the map centre.
  expect(cardBox!.y, "compact card must sit in the lower half").toBeGreaterThan(MOBILE.height / 2);
  expect(cardBox!.y + cardBox!.height).toBeLessThanOrEqual(dockBox!.y - DOCK_GAP + 0.5);

  // The upper map is clear: nothing of the card reaches the top third.
  expect(cardBox!.y).toBeGreaterThan(MOBILE.height / 3);

  // Tight card, not a stretched block.
  expect(cardBox!.height).toBeLessThan(260);
});

test("expanded inspector grows upward but stays below Row 2 and above the dock", async ({ page }) => {
  await ready(page);
  await openTrain(page);

  const card = page.locator('section[aria-label^="Inspektori"]');
  const pill = page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first();
  const dock = page.locator('[aria-label="Kontrol waktu"]');

  const compact = await card.boundingBox();
  const hero = card.locator('button[aria-controls="inspector-timeline"]');
  const close = card.getByRole("button", { name: "Tutup inspektori" });
  const header = card.locator("header");

  await hero.click();
  await expect(card.locator("#inspector-timeline")).toBeVisible();

  const expanded = await card.boundingBox();
  const row2 = await pill.boundingBox();
  const dockBox = await dock.boundingBox();

  // Grows upward from the same bottom edge.
  expect(expanded!.height).toBeGreaterThan(compact!.height);
  expect(expanded!.y + expanded!.height).toBeCloseTo(compact!.y + compact!.height, 0);

  // Strictly between Row 2's bottom and the dock's top.
  expect(expanded!.y).toBeGreaterThanOrEqual(row2!.y + row2!.height - 0.5);
  expect(expanded!.y + expanded!.height).toBeLessThanOrEqual(dockBox!.y - DOCK_GAP + 0.5);

  for (const [name, control] of [
    ["header", header],
    ["close", close],
    ["hero", hero],
  ] as const) {
    const box = await control.boundingBox();
    expect(box, `${name} must be laid out`).not.toBeNull();
    expect(box!.y).toBeGreaterThanOrEqual(expanded!.y - 1);
    expect(box!.y + box!.height).toBeLessThanOrEqual(MOBILE.height);
    expect(await isOccluded(control), `${name} must not be occluded`).toBe(false);
  }

  // Close works with a real click.
  await close.click();
  await expect(card).toHaveCount(0);
});

test("station board is bottom-anchored too", async ({ page }) => {
  await ready(page);
  await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("Gambir");
  const stationHit = page
    .locator('div[role="dialog"][aria-label="Hasil pencarian"] section[aria-label="Stasiun"] ul li button')
    .filter({ visible: true })
    .first();
  await expect(stationHit).toBeVisible({ timeout: 15_000 });
  await stationHit.click();

  const board = page.locator('section[aria-label^="Jadwal"]');
  await expect(board).toBeVisible({ timeout: 15_000 });

  const boardBox = await board.boundingBox();
  const dockBox = await page.locator('[aria-label="Kontrol waktu"]').boundingBox();
  expect(boardBox!.y).toBeGreaterThan(MOBILE.height / 2);
  expect(boardBox!.y + boardBox!.height).toBeLessThanOrEqual(dockBox!.y - DOCK_GAP + 0.5);
});

test("search dropdown still floats above the bottom-anchored inspector", async ({ page }) => {
  await ready(page);
  await openTrain(page);

  const card = page.locator('section[aria-label^="Inspektori"]');
  await card.locator('button[aria-controls="inspector-timeline"]').click();
  await expect(card.locator("#inspector-timeline")).toBeVisible();

  const before = await card.boundingBox();

  await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("Gajayana");
  const dropdown = page.locator('div[role="dialog"][aria-label="Hasil pencarian"]');
  await expect(dropdown).toBeVisible();

  // The dropdown is on top and clickable; the card did not move.
  const firstHit = dropdown.locator("ul li button").first();
  expect(await isOccluded(firstHit)).toBe(false);
  expect((await card.boundingBox())!.y).toBeCloseTo(before!.y, 0);

  // Escape restores the card's own controls.
  await page.keyboard.press("Escape");
  await expect(dropdown).toHaveCount(0);
  const hero = card.locator('button[aria-controls="inspector-timeline"]');
  expect(await isOccluded(hero)).toBe(false);
});