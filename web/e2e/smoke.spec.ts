import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(HERE, "../../data/review/web_screens");

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
});

test.beforeEach(async ({ page }) => {
  // Stub every tile request: the smoke test must not depend on the network.
  await page.route("**/tile.openstreetmap.org/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "base64",
      ),
    }),
  );
});

test("loads without console errors, shows the disclaimer and the preview banner", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto("/");
  await expect(page.locator("#disclaimer")).toContainText("bukan posisi aktual");
  await expect(page.locator("#banner")).toBeVisible();
  await expect(page.locator("#banner")).toContainText("Preview Gapeka 2026");
  await expect(page.locator("#status")).toContainText("KA aktif");
  await page.screenshot({ path: resolve(SHOTS, "01-load.png"), fullPage: true });

  expect(errors).toEqual([]);
});

test("at 2026-12-01 09:00 KA 249 is active and the search finds it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Ulang" }).click();
  await page.locator("#date").fill("2026-12-01");
  await page.locator("#time").fill(String(9 * 3600));
  await expect(page.locator("#clock")).toHaveText("09:00");

  await page.locator("#search").fill("249");
  await page.locator("#search").press("Enter");
  await expect(page.locator("#panel")).toContainText("KA 249");
  // Not merely the title: the train must actually be moving/stopped somewhere.
  await expect(page.locator("#panel")).toContainText(/Berhenti di|Menuju/);
  await page.screenshot({ path: resolve(SHOTS, "02-ka249-0900.png"), fullPage: true });
});

test("KA 260F appears at 2026-12-02 00:05 and is at Solobalapan by 00:13", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Ulang" }).click();
  await page.locator("#date").fill("2026-12-02");
  await page.locator("#time").fill(String(5 * 60));
  await expect(page.locator("#clock")).toHaveText("00:05");

  // KA 260F is fakultatif, so it is hidden until the toggle is on.
  await page.locator("#fakultatif").check();
  await page.locator("#search").fill("260F");
  await page.locator("#search").press("Enter");
  await expect(page.locator("#panel")).toContainText("KA 260F");
  await expect(page.locator("#panel")).toContainText(/Berhenti di|Menuju/);
  await page.screenshot({ path: resolve(SHOTS, "03-ka260f-0005.png"), fullPage: true });

  await page.locator("#time").fill(String(13 * 60));
  await expect(page.locator("#clock")).toHaveText("00:13");
  await expect(page.locator("#panel")).toContainText("Solobalapan");
  await page.screenshot({ path: resolve(SHOTS, "04-ka260f-0013.png"), fullPage: true });
});

test("fakultatif is hidden by default and shown when toggled", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Ulang" }).click();
  await page.locator("#date").fill("2026-12-02");
  await page.locator("#time").fill(String(5 * 60));
  await expect(page.locator("#clock")).toHaveText("00:05");

  await page.locator("#search").fill("260F");
  await page.locator("#search").press("Enter");
  await expect(page.locator("#panel")).toContainText("disembunyikan");

  await page.locator("#fakultatif").check();
  await page.locator("#search").fill("260F");
  await page.locator("#search").press("Enter");
  await expect(page.locator("#panel")).toContainText("KA 260F");
  await page.screenshot({ path: resolve(SHOTS, "05-fakultatif-on.png"), fullPage: true });
});

test("benchmark: frame time with the full schedule", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Ulang" }).click();
  await page.locator("#date").fill("2026-12-01");
  const samples: number[] = [];
  let trains = 0;
  for (let i = 0; i < 40; i += 1) {
    await page.locator("#time").fill(String(6 * 3600 + i * 60));
    await page.waitForFunction(() => window.__gapekaBench !== undefined);
    const bench = await page.evaluate(() => window.__gapekaBench!);
    samples.push(bench.frameMs);
    trains = Math.max(trains, bench.trains);
  }
  samples.sort((a, b) => a - b);
  const median = samples[Math.floor(samples.length / 2)];
  const p95 = samples[Math.floor(samples.length * 0.95)];
  const result = { samples: samples.length, median_ms: median, p95_ms: p95, max_trains: trains };
  mkdirSync(SHOTS, { recursive: true });
  const { writeFileSync } = await import("node:fs");
  writeFileSync(resolve(SHOTS, "../web_bench.json"), JSON.stringify(result, null, 1));
  expect(median).toBeLessThan(50);
});
