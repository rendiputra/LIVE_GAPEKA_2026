/**
 * Bug 2: the OpenRailwayMap mini-legend.
 *
 * Rules under test:
 * - absent while the overlay is `Default`;
 * - present while `Infrastruktur` or `Max Speed` is active;
 * - says the data is OSM/ORM community data and that maxspeed is NOT the
 *   Gapeka printed speed;
 * - never covers the time-travel dock or the train inspector.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

const DESKTOP = { width: 1280, height: 800 } as const;
const MOBILE = { width: 390, height: 844 } as const;

async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
}

/**
 * The layers control is rendered twice (desktop cluster + mobile row) and CSS
 * hides one. Only the visible instance is the one a user can click, so both
 * the trigger and the option must be selected by visibility, not DOM order.
 */
async function chooseOverlay(page: Page, label: string): Promise<void> {
  await page
    .getByRole("button", { name: "Lapisan peta" })
    .filter({ visible: true })
    .first()
    .click();
  await page
    .locator(`label:has-text("${label}")`)
    .filter({ visible: true })
    .first()
    .click();
}

async function overlaps(a: Locator, b: Locator): Promise<boolean> {
  const boxA = await a.boundingBox();
  const boxB = await b.boundingBox();
  if (!boxA || !boxB) return false;
  return !(
    boxA.x + boxA.width <= boxB.x ||
    boxB.x + boxB.width <= boxA.x ||
    boxA.y + boxA.height <= boxB.y ||
    boxB.y + boxB.height <= boxA.y
  );
}

test.describe("Bug 2 — legend", () => {
  test.use({ viewport: DESKTOP });

  test("hidden by default, shown per overlay, provenance stated", async ({ page }) => {
    await ready(page);
    const legend = page.locator('aside[aria-label="Legenda overlay rel"]');
    await expect(legend).toHaveCount(0);

    await chooseOverlay(page, "Infrastruktur");
    await expect(legend).toBeVisible();
    await expect(legend).toContainText("komunitas");
    await expect(legend).toContainText("OpenStreetMap");
    await expect(legend).toContainText("bukan Gapeka");

    // Collapsible.
    await page.getByRole("button", { name: "Sembunyikan legenda" }).click();
    await expect(legend).not.toContainText("Rel utama");
    await page.getByRole("button", { name: "Tampilkan legenda" }).click();
    await expect(legend).toContainText("Rel utama");

    // Max Speed keeps it, with its own title.
    await chooseOverlay(page, "Max Speed");
    await expect(legend).toBeVisible();
    await expect(legend).toContainText("Max Speed");

    // Back to Default removes it.
    await chooseOverlay(page, "Default");
    await expect(legend).toHaveCount(0);
  });

  test("never covers the dock or the inspector on desktop", async ({ page }) => {
    await ready(page);
    await chooseOverlay(page, "Infrastruktur");

    const legend = page.locator('aside[aria-label="Legenda overlay rel"]');
    const dock = page.locator('[aria-label="Kontrol waktu"]');
    await expect(legend).toBeVisible();
    expect(await overlaps(legend, dock)).toBe(false);

    // Open a train, then expand it: still no overlap on a wide screen.
    await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("98");
    await page.locator('div[role="dialog"][aria-label="Hasil pencarian"] ul li button').first().click();
    const inspector = page.locator('section[aria-label^="Inspektori"]');
    await expect(inspector).toBeVisible();
    await inspector.locator('button[aria-controls="inspector-timeline"]').click();
    await expect(inspector.locator("#inspector-timeline")).toBeVisible();

    await expect(legend).toBeVisible();
    expect(await overlaps(legend, inspector)).toBe(false);
    expect(await overlaps(legend, dock)).toBe(false);
  });
});

test.describe("Bug 2 — legend on mobile", () => {
  test.use({ viewport: MOBILE, isMobile: true, hasTouch: true });

  test("steps aside while a panel is open instead of covering it", async ({ page }) => {
    await ready(page);
    await chooseOverlay(page, "Infrastruktur");

    const legend = page.locator('[data-testid="overlay-legend"]');
    const dock = page.locator('[aria-label="Kontrol waktu"]');
    await expect(legend).toBeVisible();
    expect(await overlaps(legend, dock)).toBe(false);

    await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("98");
    await page.locator('div[role="dialog"][aria-label="Hasil pencarian"] ul li button').first().click();
    const inspector = page.locator('section[aria-label^="Inspektori"]');
    await expect(inspector).toBeVisible();
    await inspector.locator('button[aria-controls="inspector-timeline"]').click();
    await expect(inspector.locator("#inspector-timeline")).toBeVisible();

    // The card owns the screen: the legend is out of the way, so nothing the
    // user must tap (hero banner, close) is covered.
    await expect(legend).toBeHidden();
    const hero = inspector.locator('button[aria-controls="inspector-timeline"]');
    expect(
      await hero.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !(top === el || el.contains(top));
      }),
    ).toBe(false);

    // Closing the inspector brings the legend back.
    await inspector.getByRole("button", { name: "Tutup inspektori" }).click();
    await expect(inspector).toHaveCount(0);
    await expect(legend).toBeVisible();
  });
});