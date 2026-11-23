/**
 * Bug 4: the map warning must use plain Indonesian.
 *
 * MapLibre treats a tile HTTP 404 as an empty tile, not an error, so the route
 * must fail with a server error (500) to exercise the real `map.on("error")`
 * wiring. The assertion is on the sentence a user actually reads.
 */
import { expect, test } from "@playwright/test";

test("a failed tile shows 'Sebagian layer peta belum termuat'", async ({ page }) => {
  await page.route("**/tiles.openfreemap.org/planet/**", (route) =>
    route.fulfill({ status: 500, contentType: "text/plain", body: "boom" }),
  );

  await page.goto("/");
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  const warning = page.getByText("Sebagian layer peta belum termuat");
  await expect(warning.first()).toBeVisible({ timeout: 30_000 });

  // The old wording must be gone entirely.
  await expect(page.getByText("Ada ubin yang belum termuat")).toHaveCount(0);
});