/**
 * Fix 4: the legend must describe the overlay that is actually active.
 *
 * `Infrastruktur` and `Max Speed` render different OSM tags, so a shared row
 * list is factually wrong: the QA saw "Rel utama / siding / yard / wissel"
 * under a `Legenda Max Speed` heading, and the legend covered MapLibre's
 * bottom-right zoom/compass cluster.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

const DESKTOP = { width: 1280, height: 800 } as const;

async function ready(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
}

async function chooseOverlay(page: Page, label: string): Promise<void> {
  await page
    .getByRole("button", { name: "Lapisan peta" })
    .filter({ visible: true })
    .first()
    .click();
  await page.getByRole("radio", { name: label }).filter({ visible: true }).first().click();
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

test.use({ viewport: DESKTOP });

test("Max Speed shows speed bands and no infrastructure vocabulary", async ({ page }) => {
  await ready(page);
  await chooseOverlay(page, "Max Speed");

  const legend = page.locator('aside[aria-label="Legenda overlay rel"]');
  await expect(legend).toBeVisible();
  await expect(legend).toContainText("Legenda Max Speed");

  const text = await legend.innerText();
  expect(text).toContain("80–120");
  expect(text).toContain("km/j");
  expect(text).toContain("> 200");
  expect(text).toContain("belum ada tag maxspeed");
  // The reported bug: infrastructure vocabulary under a speed heading.
  expect(text).not.toContain("wissel");
  expect(text).not.toContain("kruiswissel");
  expect(text).not.toContain("Rel utama");
  expect(text).not.toContain("yard");

  // Provenance stays explicit.
  expect(text).toContain("komunitas");
  expect(text).toContain("Bukan data Gapeka");
});

test("Infrastruktur shows its own rows, not speed bands", async ({ page }) => {
  await ready(page);
  await chooseOverlay(page, "Infrastruktur");

  const legend = page.locator('aside[aria-label="Legenda overlay rel"]');
  await expect(legend).toContainText("Legenda Infrastruktur");

  const text = await legend.innerText();
  expect(text).toContain("Rel utama");
  expect(text).toContain("Wesel");
  expect(text).not.toContain("km/j");
  expect(text).not.toContain("80–120");
});

test("legend never covers the zoom controls, attribution, dock or inspector", async ({ page }) => {
  await ready(page);
  await chooseOverlay(page, "Max Speed");

  const legend = page.locator('aside[aria-label="Legenda overlay rel"]');
  await expect(legend).toBeVisible();

  const zoom = page.locator(".maplibregl-ctrl-group").first();
  const attrib = page.locator(".maplibregl-ctrl-attrib").first();
  const dock = page.locator('[aria-label="Kontrol waktu"]');

  expect(await overlaps(legend, zoom), "legend vs zoom").toBe(false);
  expect(await overlaps(legend, attrib), "legend vs attribution").toBe(false);
  expect(await overlaps(legend, dock), "legend vs dock").toBe(false);

  // Fully on screen.
  const box = await legend.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(DESKTOP.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(DESKTOP.height);

  // No inner scrollbar: the row list is short enough to fit.
  const scrolls = await legend.evaluate((el) => {
    const scroller = el.querySelector("div.overflow-y-auto");
    return scroller ? scroller.scrollHeight > scroller.clientHeight + 1 : false;
  });
  expect(scrolls, "legend must not need an inner scrollbar").toBe(false);
});