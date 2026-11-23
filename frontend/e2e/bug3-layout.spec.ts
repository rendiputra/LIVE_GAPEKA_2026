/**
 * Bug 3 regressions: layout, z-index and hit-testing.
 *
 * Runs against the PRODUCTION build (`frontend/dist` via vite preview).
 * Every interaction is a real click — no `{ force: true }` — so an element
 * covered by another layer fails the test instead of silently passing.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

const DESKTOP = { width: 1280, height: 800 } as const;
const MOBILE = { width: 390, height: 844 } as const;

/** True when the element's centre point is covered by something else. */
async function isOccluded(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const top = document.elementFromPoint(x, y);
    if (!top) return true;
    return !(top === element || element.contains(top));
  });
}

/**
 * The status pill exists twice (desktop cluster + mobile row 2) and CSS hides
 * one of them. Only the VISIBLE instance is the one a user can see, so every
 * assertion must select by visibility rather than DOM order.
 */
function visiblePill(page: Page): Locator {
  return page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first();
}

async function desktopReady(page: Page): Promise<void> {
  await page.goto("/?e2e=1");
  await page.waitForFunction(
    () => Boolean((window as unknown as { __liveMap?: unknown }).__liveMap),
    undefined,
    { timeout: 30_000 },
  );
  await expect(visiblePill(page)).toBeVisible({ timeout: 30_000 });
}

async function openTrain(page: Page, query = "98"): Promise<void> {
  await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill(query);
  const hit = page.locator('div[role="dialog"][aria-label="Hasil pencarian"] ul li button').first();
  await expect(hit).toBeVisible({ timeout: 15_000 });
  await hit.click();
  await expect(page.locator('section[aria-label^="Inspektori"]')).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("Bug 3 — desktop 1280x800", () => {
  test.use({ viewport: DESKTOP });

  test("Filter button opens a real popover and toggles the switch", async ({ page }) => {
    await desktopReady(page);

    const filter = page.getByRole("button", { name: "Filter kereta" });
    await expect(filter).toBeVisible();
    expect(await isOccluded(filter)).toBe(false);

    await filter.click(); // no force
    const popover = page.locator('div[role="dialog"][aria-label="Filter kereta"]');
    await expect(popover).toBeVisible();
    await expect(popover).toContainText("Tampilkan KA fakultatif");
    await expect(popover).toContainText("Nonaktif (default)");

    const checkbox = popover.getByRole("checkbox", { name: "Tampilkan KA fakultatif" });
    await expect(checkbox).not.toBeChecked();
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await expect(popover).toContainText("Aktif");
    await expect(filter).toHaveAttribute("aria-pressed", "true");

    // Escape closes only the popover.
    await page.keyboard.press("Escape");
    await expect(popover).toHaveCount(0);
    await expect(filter).toHaveAttribute("aria-pressed", "true");

    // Second click opens again; outside click closes.
    await filter.click();
    await expect(popover).toBeVisible();
    await page.locator('[data-testid="live-map"] canvas').first().click({ position: { x: 900, y: 600 } });
    await expect(popover).toHaveCount(0);
  });

  test("Inspector header, Close and hero stay reachable while expanded", async ({ page }) => {
    await desktopReady(page);
    await openTrain(page);

    const inspector = page.locator('section[aria-label^="Inspektori"]');
    const hero = inspector.locator('button[aria-controls="inspector-timeline"]');
    const close = inspector.getByRole("button", { name: "Tutup inspektori" });

    // Compact first: the full stop list must not be rendered.
    await expect(inspector.locator("#inspector-timeline")).toHaveCount(0);

    await hero.click(); // real click
    const timeline = inspector.locator("#inspector-timeline");
    await expect(timeline).toBeVisible();

    for (const control of [hero, close]) {
      const box = await control.boundingBox();
      expect(box, "control must be laid out").not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(DESKTOP.height);
      expect(await isOccluded(control)).toBe(false);
    }

    const closeBox = await close.boundingBox();
    expect(closeBox!.width).toBeGreaterThanOrEqual(36);
    expect(closeBox!.height).toBeGreaterThanOrEqual(36);

    // Collapse by clicking the hero again — still reachable while expanded.
    await hero.click();
    await expect(timeline).toHaveCount(0);
    await expect(inspector).toBeVisible();

    // And the Close button still closes without a refresh.
    await close.click();
    await expect(inspector).toHaveCount(0);
  });

  test("Search dropdown floats above the expanded inspector and Escape restores it", async ({ page }) => {
    await desktopReady(page);
    await openTrain(page);

    const inspector = page.locator('section[aria-label^="Inspektori"]');
    const hero = inspector.locator('button[aria-controls="inspector-timeline"]');
    const close = inspector.getByRole("button", { name: "Tutup inspektori" });

    await hero.click();
    await expect(inspector.locator("#inspector-timeline")).toBeVisible();

    // The inspector must NOT move when Search opens.
    const beforeBox = await inspector.boundingBox();

    await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("Gajayana");
    const dropdown = page.locator('div[role="dialog"][aria-label="Hasil pencarian"]');
    await expect(dropdown).toBeVisible();

    const afterBox = await inspector.boundingBox();
    expect(Math.abs(afterBox!.y - beforeBox!.y)).toBeLessThanOrEqual(1);

    const firstResult = dropdown.locator("ul li button").first();
    await expect(firstResult).toBeVisible();
    expect(await isOccluded(firstResult)).toBe(false);
    await firstResult.click(); // real click proves it is on top

    // Selecting a train collapses the timeline back to compact.
    await expect(inspector.locator("#inspector-timeline")).toHaveCount(0);

    // Reopen the list, then Escape closes the inspector as the last layer.
    await hero.click();
    await expect(inspector.locator("#inspector-timeline")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(inspector).toHaveCount(0);
    expect(await close.count()).toBe(0);
  });

  test("MapLibre zoom buttons are visible on desktop", async ({ page }) => {
    await desktopReady(page);
    await expect(page.locator(".maplibregl-ctrl-group").first()).toBeVisible();
  });
});

test.describe("Bug 3 — mobile 390x844", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("top stack never overlaps and the status pill is fully readable", async ({ page }) => {
    await desktopReady(page);

    const search = page.getByLabel(/Cari KA, nama kereta atau stasiun/i);
    const filter = page.getByRole("button", { name: "Filter kereta" });
    const about = page.getByRole("button", { name: "Tentang aplikasi ini" });
    const pill = visiblePill(page);
    const layers = page
      .getByRole("button", { name: "Lapisan peta" })
      .filter({ visible: true })
      .first();

    for (const control of [search, filter, about, pill, layers]) {
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE.width + 0.5);
      expect(await isOccluded(control)).toBe(false);
    }

    // Row 1 controls sit above row 2's pill (no vertical overlap).
    const searchBox = await search.boundingBox();
    const pillBox = await pill.boundingBox();
    expect(pillBox!.y).toBeGreaterThanOrEqual(searchBox!.y + searchBox!.height);

    // No horizontal collision between the Filter button and the pill.
    const filterBox = await filter.boundingBox();
    expect(filterBox!.y + filterBox!.height).toBeLessThanOrEqual(pillBox!.y + 0.5);
  });

  test("Filter popover works on mobile with real clicks", async ({ page }) => {
    await desktopReady(page);

    const filter = page.getByRole("button", { name: "Filter kereta" });
    expect(await isOccluded(filter)).toBe(false);
    await filter.click();

    const popover = page.locator('div[role="dialog"][aria-label="Filter kereta"]');
    await expect(popover).toBeVisible();
    const box = await popover.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE.width + 0.5);

    const checkbox = popover.getByRole("checkbox", { name: "Tampilkan KA fakultatif" });
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await expect(filter).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");
    await expect(popover).toHaveCount(0);
  });

  test("expanded inspector stays clear of the top stack and the dock", async ({ page }) => {
    await desktopReady(page);
    await openTrain(page);

    const inspector = page.locator('section[aria-label^="Inspektori"]');
    const hero = inspector.locator('button[aria-controls="inspector-timeline"]');
    const close = inspector.getByRole("button", { name: "Tutup inspektori" });

    await hero.click();
    await expect(inspector.locator("#inspector-timeline")).toBeVisible();

    // The card never covers the top controls.
    const pill = visiblePill(page);
    const pillBox = await pill.boundingBox();
    const cardBox = await inspector.boundingBox();
    expect(cardBox!.y).toBeGreaterThanOrEqual(pillBox!.y + pillBox!.height - 0.5);

    for (const control of [hero, close]) {
      expect(await isOccluded(control)).toBe(false);
      const box = await control.boundingBox();
      expect(box!.y + box!.height).toBeLessThanOrEqual(MOBILE.height);
    }

    const closeBox = await close.boundingBox();
    expect(closeBox!.width).toBeGreaterThanOrEqual(36);
    expect(closeBox!.height).toBeGreaterThanOrEqual(36);

    // Search floats above the card; Escape then Close both work.
    await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("Gajayana");
    const dropdown = page.locator('div[role="dialog"][aria-label="Hasil pencarian"]');
    await expect(dropdown).toBeVisible();
    const firstResult = dropdown.locator("ul li button").first();
    expect(await isOccluded(firstResult)).toBe(false);

    await page.keyboard.press("Escape");
    await expect(dropdown).toHaveCount(0);
    await expect(inspector).toBeVisible();

    await close.click();
    await expect(inspector).toHaveCount(0);
  });

  test("MapLibre zoom controls are hidden; attribution stays visible", async ({ page }) => {
    await desktopReady(page);
    // display:none keeps the node in the DOM, so assert computed style rather
    // than element count.
    const hidden = await page.locator(".maplibregl-ctrl-group").first().evaluate(
      (el) => getComputedStyle(el as HTMLElement).display,
    );
    expect(hidden).toBe("none");
    await expect(page.locator(".maplibregl-ctrl-attrib").first()).toBeVisible();
  });
});
