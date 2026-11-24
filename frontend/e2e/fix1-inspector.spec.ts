/**
 * Fix 1: the Train Inspector must wrap its own content when compact, and must
 * keep its identity header, Close button and Next Stop banner inside the
 * viewport when expanded.
 *
 * Runs against the production build (frontend/dist) with real clicks.
 */
import { expect, test, type Page } from "@playwright/test";

const DESKTOP = { width: 1280, height: 800 } as const;
const MOBILE = { width: 390, height: 844 } as const;

const COMPACT_MAX_HEIGHT = 260;

async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
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

/** True when the element's centre is covered by another element. */
async function isOccluded(locator: import("@playwright/test").Locator): Promise<boolean> {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!top) return true;
    return !(top === element || element.contains(top));
  });
}

for (const [label, viewport] of [
  ["desktop", DESKTOP],
  ["mobile", MOBILE],
] as const) {
  test.describe(`Fix 1 — ${label} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("compact card wraps its content instead of stretching", async ({ page }) => {
      await ready(page);
      await openTrain(page);

      const card = page.locator('section[aria-label^="Inspektori"]');
      const box = await card.boundingBox();
      expect(box).not.toBeNull();

      // The bug: the card filled a top→bottom wrapper (574px desktop, 612px
      // mobile) leaving a large blank white block.
      expect(box!.height).toBeLessThan(COMPACT_MAX_HEIGHT);
      expect(box!.height).toBeGreaterThan(120);

      // And it still fits on screen.
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    });

    test("expanded card pins header, Close and Next Stop banner", async ({ page }) => {
      await ready(page);
      await openTrain(page);

      const card = page.locator('section[aria-label^="Inspektori"]');
      const compactBox = await card.boundingBox();

      const hero = card.locator('button[aria-controls="inspector-timeline"]');
      const close = card.getByRole("button", { name: "Tutup inspektori" });
      const header = card.locator("header");

      await hero.click();
      await expect(card.locator("#inspector-timeline")).toBeVisible();

      // The card may grow, but never beyond the safe area.
      const expandedBox = await card.boundingBox();
      expect(expandedBox!.height).toBeGreaterThanOrEqual(compactBox!.height);

      for (const [name, control] of [
        ["header", header],
        ["close", close],
        ["hero", hero],
      ] as const) {
        const box = await control.boundingBox();
        expect(box, `${name} must be laid out`).not.toBeNull();
        // The bug: the header rendered at y=10 while its card started at y=136.
        expect(box!.y, `${name} top`).toBeGreaterThanOrEqual(expandedBox!.y - 1);
        expect(box!.y + box!.height, `${name} bottom`).toBeLessThanOrEqual(viewport.height);
        expect(await isOccluded(control), `${name} must not be occluded`).toBe(false);
      }

      const closeBox = await close.boundingBox();
      expect(closeBox!.width).toBeGreaterThanOrEqual(36);
      expect(closeBox!.height).toBeGreaterThanOrEqual(36);

      // The Close button really closes, with no refresh.
      await close.click();
      await expect(card).toHaveCount(0);
    });
  });
}
