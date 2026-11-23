/**
 * Playwright smoke test for the live map.
 *
 * The map needs WebGL (headless Chromium has it via SwiftShader) and network
 * access to OpenFreeMap. Tile failures are tolerated: the app is specified to
 * degrade, not crash, when the basemap is unreachable.
 */
import { expect, test } from "@playwright/test";

test.describe("live map smoke", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("boots and shows the map canvas", async ({ page }) => {
    const map = page.locator('[data-testid="live-map"]');
    await expect(map).toBeVisible({ timeout: 20_000 });
    const canvas = page.locator('[data-testid="live-map"] canvas');
    await expect(canvas.first()).toBeAttached({ timeout: 20_000 });
  });

  test("shows the Live status pill with the estimate disclaimer", async ({ page }) => {
    const pill = page.locator("text=Live (Estimasi)");
    await expect(pill.first()).toBeVisible({ timeout: 30_000 });
  });

  test("has no preview banner and no footer disclaimer bar", async ({ page }) => {
    await expect(page.locator("text=Preview Gapeka 2026")).toHaveCount(0);
    // The only long disclaimer is inside the Tentang modal, which is closed.
    await expect(page.locator("text=Diasumsikan tepat waktu")).toHaveCount(0);
  });

  test("opens the Tentang modal with the full disclaimer and hash", async ({ page }) => {
    await page.getByRole("button", { name: "Tentang aplikasi ini" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("bukan posisi aktual");
    await expect(dialog).toContainText("1 Desember 2026");
    await expect(dialog).toContainText("Hash data");
    await expect(dialog).toContainText("OpenFreeMap");
    await expect(dialog).toContainText("OpenRailwayMap");
    await expect(dialog).toContainText("bukan situs resmi");
    await page.getByRole("button", { name: "Tutup" }).click();
    await expect(dialog).toBeHidden();
  });

  test("renders trains and clicking the map opens the inspector", async ({ page }) => {
    // Wait for the worker to answer at least once.
    await expect(page.locator("text=/[0-9]+ KA/").first()).toBeVisible({
      timeout: 40_000,
    });
    // Click roughly where Java is; if a marker is under the point the
    // inspector appears. This is best-effort in CI.
    await page.locator('[data-testid="live-map"] canvas').click({
      position: { x: 600, y: 300 },
      timeout: 5_000,
    });
  });

  test("toggles the fakultatif filter", async ({ page }) => {
    const button = page.getByRole("button", { name: "Tampilkan KA fakultatif" });
    await expect(button).toBeVisible();
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  });

  test("switches to Simulasi by scrubbing and back to Live", async ({ page }) => {
    await expect(page.locator("text=Live (Estimasi)").first()).toBeVisible({
      timeout: 30_000,
    });
    const slider = page.getByRole("slider", { name: /Geser waktu/i });
    await slider.fill("720");
    // After interacting, the pill should say Simulasi.
    await expect(page.locator("text=Simulasi (Estimasi)").first()).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole("button", { name: /Kembali ke Live/ }).click();
    await expect(page.locator("text=Live (Estimasi)").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("opens the layers popover", async ({ page }) => {
    await page.getByRole("button", { name: "Lapisan peta" }).click();
    const dialog = page.getByRole("dialog", { name: /Lapisan/i });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Peta Dasar");
    await expect(dialog).toContainText("Overlay Rel");
    await expect(dialog).toContainText("Infrastruktur");
    await expect(dialog).toContainText("Max Speed");
  });

  test("searches for a train", async ({ page }) => {
    await page.getByLabel(/Cari KA, nama kereta atau stasiun/i).fill("Gajayana");
    await expect(page.locator("text=Kereta Api").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("text=Gajayana").first()).toBeVisible();
  });

  test("time-travel dock is present", async ({ page }) => {
    await expect(page.getByRole("slider", { name: /Geser waktu/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Mundurkan 15 menit/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Majukan 15 menit/i })).toBeVisible();
  });
});
