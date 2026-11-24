/**
 * Fix 5: on a phone MapLibre's attribution must start collapsed.
 *
 * `AttributionControl({ compact: true })` is not enough: MapLibre still renders
 * the compact control EXPANDED on first paint, and the expanded line ran under
 * the time-travel dock, which sits at the bottom centre of a 390px screen.
 */
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test("attribution starts collapsed and clears the dock", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  const attrib = page.locator(".maplibregl-ctrl-attrib").first();
  await expect(attrib).toBeAttached();

  // The expanded state is the bug: `maplibregl-compact-show` prints the full
  // licence line.
  await expect
    .poll(async () => attrib.evaluate((el) => el.classList.contains("maplibregl-compact-show")), {
      timeout: 15_000,
    })
    .toBe(false);

  // Only the (i) button remains, and it is reachable.
  const button = page.locator(".maplibregl-ctrl-attrib-button").first();
  await expect(button).toBeVisible();
  expect(
    await button.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return !(top === el || el.contains(top));
    }),
    "the attribution button must not be covered",
  ).toBe(false);

  // Collapsed means it no longer collides with the dock.
  const dock = await page.locator('[aria-label="Kontrol waktu"]').boundingBox();
  const box = await attrib.boundingBox();
  expect(box).not.toBeNull();
  expect(dock).not.toBeNull();
  const intersects = !(
    box!.x + box!.width <= dock!.x ||
    dock!.x + dock!.width <= box!.x ||
    box!.y + box!.height <= dock!.y ||
    dock!.y + dock!.height <= box!.y
  );
  expect(intersects, "attribution must not overlap the dock").toBe(false);

  // The licence text stays in the DOM even while collapsed, so assistive tech
  // and crawlers still get it (MapLibre hides it with CSS, not by removing it).
  await expect(attrib.locator(".maplibregl-ctrl-attrib-inner")).toBeAttached();
  await expect(attrib).toContainText("OpenStreetMap");
});