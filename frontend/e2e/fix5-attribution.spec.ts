/**
 * Fix 5b: MapLibre's attribution is a native `<details>` element.
 *
 * `_updateCompact()` opens it on first paint (`open` + `compact-show`), which
 * prints the full licence line across the bottom of a 390px screen. Collapsing
 * means REMOVING `open` — not setting it — and dropping `compact-show` once.
 * With no MutationObserver in the way, the native summary toggle still works:
 * tapping (i) expands and collapses the licence text.
 */
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const COLLAPSED_MAX_WIDTH = 48;

test("attribution starts collapsed as the compact (i) and toggles natively", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  const attribution = page.locator(".maplibregl-ctrl-attrib").first();
  await expect(attribution).toBeAttached();

  // Give MapLibre time to run its own compact recomputation, then assert the
  // native closed state survives it.
  await page.waitForTimeout(2_500);
  await expect
    .poll(async () => attribution.evaluate((el) => el.hasAttribute("open")), { timeout: 15_000 })
    .toBe(false);

  const collapsed = await attribution.boundingBox();
  expect(collapsed).not.toBeNull();
  expect(collapsed!.width, "collapsed means only the (i) button").toBeLessThanOrEqual(
    COLLAPSED_MAX_WIDTH,
  );

  // Clear of the dock (and therefore of the bottom-anchored inspector).
  const dock = await page.locator('[aria-label="Kontrol waktu"]').boundingBox();
  const intersects =
    collapsed!.x + collapsed!.width > dock!.x &&
    dock!.x + dock!.width > collapsed!.x &&
    collapsed!.y + collapsed!.height > dock!.y &&
    dock!.y + dock!.height > collapsed!.y;
  expect(intersects, "attribution must not overlap the dock").toBe(false);

  // The (i) button is present, reachable and carries an accessible name.
  const button = page.locator(".maplibregl-ctrl-attrib-button").first();
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("aria-label", /attribution/i);
  expect(
    await button.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return !(top === el || el.contains(top));
    }),
  ).toBe(false);

  // Native toggle: tap opens the licence text, tap again closes it.
  await button.click();
  await expect
    .poll(async () => attribution.evaluate((el) => el.hasAttribute("open")))
    .toBe(true);
  const expanded = await attribution.boundingBox();
  expect(expanded!.width).toBeGreaterThan(COLLAPSED_MAX_WIDTH);
  await expect(attribution).toContainText("OpenStreetMap");

  await button.click();
  await expect
    .poll(async () => attribution.evaluate((el) => el.hasAttribute("open")))
    .toBe(false);
});

test("desktop attribution is untouched by the mobile collapse", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });
  const attribution = page.locator(".maplibregl-ctrl-attrib").first();
  await expect(attribution).toContainText("OpenStreetMap");
});