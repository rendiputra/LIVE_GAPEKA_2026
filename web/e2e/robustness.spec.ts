// T7: robustness. Timezone independence, the pre-release banner flip, a
// sub-path deployment, and accessibility.
//
// These are separate from the smoke test because they need their own browser
// contexts or servers.

import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
/** The controls are inert until the app has wired its handlers. */
async function waitReady(page: import("@playwright/test").Page): Promise<void> {
  await page.locator('body[data-app-ready="true"]').waitFor({ state: "attached" });
}

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REVIEW = resolve(HERE, "../../data/review");
const SUBPATH_URL = "http://127.0.0.1:4174/sub/";

test.beforeAll(() => {
  mkdirSync(REVIEW, { recursive: true });
});

test.beforeEach(async ({ page }) => {
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

test("positions are identical in three browser timezones", async ({ browser }) => {
  const timezones = ["Asia/Jakarta", "America/New_York", "Pacific/Auckland"];
  const records: Array<{ timezoneId: string; status: string; rows: string[] }> = [];

  for (const timezoneId of timezones) {
    const context = await browser.newContext({ timezoneId });
    const page = await context.newPage();
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
    // `browser.newContext()` does not inherit `use.baseURL`.
    await page.goto("http://127.0.0.1:4173/");
    await waitReady(page);
    await expect(page.locator("#loading")).toBeHidden();
    await page.getByRole("radio", { name: "Ulang" }).click();
    await page.locator("#date").fill("2026-12-01");
    await page.locator("#time").fill(String(9 * 3600));
    await expect(page.locator("#clock")).toHaveText("09:00");
    // The status only carries the service date in REPLAY mode, so this waits for
    // a replay frame to have rendered. A live frame would satisfy a looser check
    // and make the comparison meaningless.
    await expect(page.locator("#status")).toContainText("2026-12-01");
    await expect(page.locator("#status")).toContainText(/[1-9]\d* KA aktif/);

    // The panel content is the strongest signal: same trains, same order, same
    // printed times, regardless of the browser timezone.
    await page.locator("#search").fill("249");
    await page.locator("#search").press("Enter");
    await expect(page.locator("#panel")).toContainText("KA 249");
    const rows = await page.locator("#panel li").allTextContents();

    records.push({
      timezoneId,
      status: (await page.locator("#status").textContent()) ?? "",
      rows: rows.map((row) => row.replace(/\s+/g, " ").trim()),
    });
    await context.close();
  }

  writeFileSync(
    resolve(REVIEW, "timezone_parity.json"),
    JSON.stringify(records, null, 2),
  );

  const [first, ...rest] = records;
  for (const record of rest) {
    expect(record.status, record.timezoneId).toBe(first.status);
    expect(record.rows, record.timezoneId).toEqual(first.rows);
  }
  expect(first.status).toContain("WIB");
  expect(first.rows.length).toBeGreaterThan(0);
});

test("the preview banner flips exactly at 2026-12-01T00:00+07:00", async ({ page }) => {
  // 2026-11-30T16:59Z is 23:59 WIB on 30 November.
  await page.clock.install({ time: new Date("2026-11-30T16:59:00Z") });
  await page.goto("/");
  await waitReady(page);
  await expect(page.locator("#banner")).toBeVisible();

  // 2026-11-30T17:01Z is 00:01 WIB on 1 December.
  await page.clock.setSystemTime(new Date("2026-11-30T17:01:00Z"));
  await page.getByRole("radio", { name: "Ulang" }).click();
  await expect(page.locator("#banner")).toBeHidden();
});

test("works when served under a sub-path, including the worker fetch", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto(SUBPATH_URL);
  await waitReady(page);
  await expect(page.locator("#status")).toContainText("KA aktif");
  await expect(page.locator("#loading")).toBeHidden();
  expect(errors).toEqual([]);
});

test("has no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await waitReady(page);
  // The handlers are wired after the data loads, so wait for that first.
  await expect(page.locator("#loading")).toBeHidden();
  await expect(page.locator("#status")).toContainText(/[1-9]\d* KA aktif/);
  await page.locator("#about-open").click();
  await expect(page.locator("#about")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const serious = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );

  writeFileSync(
    resolve(REVIEW, "axe_report.json"),
    JSON.stringify(
      {
        violations: results.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          description: violation.description,
          nodes: violation.nodes.map((node) => node.target.join(" ")),
        })),
        serious_or_critical: serious.length,
      },
      null,
      2,
    ),
  );

  expect(serious, serious.map((violation) => violation.id).join(", ")).toEqual([]);
});
