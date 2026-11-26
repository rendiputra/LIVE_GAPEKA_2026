// Acceptance suite for the frontend revamp (Turn 3b).
//
// Runs at BOTH required viewports: Desktop 1280x800 and Mobile 390x844. Every
// interaction is a real click or keypress — there is no `{ force: true }` in this
// file or anywhere in `e2e/`, because forcing a click hides exactly the
// "element is covered / not reachable" defects this suite exists to find.
//
// Covers, in order:
//   1. clean load, 391 rail lines, station labels
//   2. live motion actually advancing
//   3. KA 249: compact -> expanded -> collapse
//   4. midnight tail: KA 260F on the next service date
//   5. time-travel and "Kembali ke Live"
//   6. Layers radios + OpenRailwayMap "Max Speed" legend
//   7. search, including stations without coordinates (STM / CIK / TPR)
//   8. Filter popover
//   9. Tentang modal disclaimer
//  10. timezone invariance (Asia/Jakarta vs America/New_York)

import { expect, test, type Locator, type Page } from "@playwright/test";

const RAIL_SEGMENTS = 391;

/** Wait until the schedule has loaded and the live clock is running. */
async function ready(page: Page): Promise<void> {
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 40_000,
  });
}

/** The map container carries read-only counts for rails and station labels. */
async function mapCount(page: Page, attribute: string): Promise<number> {
  const map = page.locator('[data-testid="live-map"]');
  await expect.poll(async () => map.getAttribute(attribute), { timeout: 30_000 }).not.toBeNull();
  return Number(await map.getAttribute(attribute));
}

/** Assert a control is fully inside the viewport (no clipped edges). */
async function expectInsideViewport(page: Page, locator: Locator, label: string): Promise<void> {
  const box = await locator.boundingBox();
  const size = page.viewportSize();
  expect(box, `${label} must be laid out`).not.toBeNull();
  expect(size).not.toBeNull();
  expect(box!.x, `${label} left edge`).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, `${label} right edge`).toBeLessThanOrEqual(size!.width + 0.5);
  expect(box!.y, `${label} top edge`).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, `${label} bottom edge`).toBeLessThanOrEqual(size!.height + 0.5);
}

async function search(page: Page, query: string): Promise<void> {
  // Two search inputs exist once the results panel is open (the main one and
  // the panel's own). The main one is #search.
  await page.locator("#search").fill(query);
}

async function openTrain(page: Page, trainNo: string): Promise<void> {
  await search(page, trainNo);
  const results = page.getByRole("dialog", { name: "Hasil pencarian" });
  await expect(results).toBeVisible({ timeout: 15_000 });
  await results
    .getByRole("region", { name: "Kereta Api" })
    .getByRole("button")
    .first()
    .click();
}

test.beforeEach(async ({ page }) => {
  await page.route("**/*tile*", (route) => route.abort());
  await page.route("**/*.pmtiles*", (route) => route.abort());
});

test("1. loads cleanly with 391 rail lines and station labels", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error" && !/tile|pmtiles|Failed to fetch/i.test(message.text())) {
      errors.push(message.text());
    }
  });

  await page.goto("/");
  await ready(page);

  await expect(page.locator('[data-testid="live-map"] canvas')).toBeAttached();
  expect(await mapCount(page, "data-rail-features")).toBe(RAIL_SEGMENTS);
  // Labels come from the exported stations; any positive count proves the
  // source is populated (individual symbols depend on zoom and placement).
  expect(await mapCount(page, "data-station-features")).toBeGreaterThan(100);

  // The estimate status must be stated at all times (ADR 002 amendment).
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toContainText(/WIB/);
  expect(errors).toEqual([]);
});

test("2. live motion advances over time", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  expect(await mapCount(page, "data-rail-features")).toBe(RAIL_SEGMENTS);

  // The pill only shows HH:MM, so waiting for it would take a minute. The map
  // publishes the wall-clock of its last train update instead: if that keeps
  // advancing, the live clock is actually driving the markers.
  const map = page.locator('[data-testid="live-map"]');
  await expect
    .poll(async () => Number(await map.getAttribute("data-train-updated")), {
      timeout: 20_000,
      intervals: [250],
    })
    .toBeGreaterThan(0);
  const first = Number(await map.getAttribute("data-train-updated"));

  await expect
    .poll(async () => Number(await map.getAttribute("data-train-updated")), {
      timeout: 20_000,
      intervals: [500],
    })
    .toBeGreaterThan(first);
});

test("3. KA 249 opens compact, expands, and collapses", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  await openTrain(page, "249");

  const inspector = page.getByRole("region", { name: /Inspektori KA 249/i });
  await expect(inspector).toBeVisible({ timeout: 15_000 });

  const banner = inspector.getByRole("button", { expanded: false });
  await expect(banner).toBeVisible();
  await banner.click();

  await expect(inspector.getByRole("button", { expanded: true })).toBeVisible();
  await expect(inspector.getByRole("button", { name: /Tutup inspektori/i })).toBeVisible();

  // Collapse again via the same hero banner.
  await inspector.getByRole("button", { expanded: true }).click();
  await expect(inspector.getByRole("button", { expanded: false })).toBeVisible();
});

test("4. midnight tail: KA 260F is active just after midnight", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  // KA 260F is fakultatif, so the default policy hides it. Enabling the filter
  // is part of the scenario, not a workaround: a fakultatif train must never
  // appear without the user asking for it.
  await page.getByRole("button", { name: "Filter kereta" }).filter({ visible: true }).first().click();
  await page
    .getByRole("dialog", { name: "Filter kereta" })
    .filter({ visible: true })
    .getByRole("checkbox", { name: /Tampilkan KA fakultatif/i })
    .check();
  await page.keyboard.press("Escape");

  // 00:05. At that instant the only running KA 260F is the one that departed
  // 22:05 on the PREVIOUS service date, which is the tail this test guards.
  await page.getByRole("slider", { name: /Geser waktu/i }).fill("5");
  await expect(page.getByText(/Simulasi \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 15_000,
  });

  // Assert against the active-train list, not the inspector: searching "260F"
  // selects today's run, which legitimately has not departed yet at 00:05.
  const map = page.locator('[data-testid="live-map"]');
  await expect
    .poll(async () => (await map.getAttribute("data-train-numbers")) ?? "", {
      timeout: 20_000,
    })
    .toContain("260F");
});

test("5. time-travel reaches Simulasi and Kembali ke Live returns", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  const slider = page.getByRole("slider", { name: /Geser waktu/i });
  const dock = page.locator('[aria-label="Kontrol waktu"]');
  await expectInsideViewport(page, dock, "dock in Live");

  await slider.fill("720");
  await expect(page.getByText(/Simulasi \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 15_000,
  });

  // Simulasi adds the "Kembali ke Live" button. On a 390px phone that used to
  // widen the dock to 429px and push both edges off-screen (measured), so the
  // dock must stay inside the viewport in BOTH modes.
  await expectInsideViewport(page, dock, "dock in Simulasi");

  await page.getByRole("button", { name: /Kembali ke Live/i }).click();
  await expect(page.getByText(/Live \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
    timeout: 15_000,
  });
  await expectInsideViewport(page, dock, "dock after returning to Live");
});

test("6. Layers radios select, and Max Speed shows a speed legend", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  await page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Lapisan peta" }).filter({ visible: true });
  await expect(dialog).toBeVisible();

  const layersButton = page.getByRole("button", { name: "Lapisan peta" }).filter({ visible: true }).first();
  const openLayers = async () => {
    await layersButton.click();
    const panel = page.getByRole("dialog", { name: "Lapisan peta" }).filter({ visible: true });
    await expect(panel).toBeVisible();
    return panel;
  };

  // The default radio must be visibly selected (the "empty circles" bug).
  await expect(dialog.getByRole("radio", { name: /Clean \(Positron\)/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );

  // Selecting an option closes the panel by design, so the choice is verified
  // by reopening it rather than by watching the closed panel.
  await dialog.getByRole("radio", { name: /Detail \(Liberty\)/ }).click();
  await expect(dialog).toBeHidden();
  const reopened = await openLayers();
  await expect(reopened.getByRole("radio", { name: /Detail \(Liberty\)/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );

  // OpenRailwayMap overlay with a real speed legend.
  await reopened.getByRole("radio", { name: /Max Speed/ }).click();
  const legend = page.locator('[data-testid="overlay-legend"]');
  await expect(legend).toBeVisible({ timeout: 15_000 });
  await expect(legend).toContainText(/km\/j/i);
  const afterOverlay = await openLayers();
  await expect(afterOverlay.getByRole("radio", { name: /Max Speed/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});

test("7. search finds a train and stations without coordinates", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  // A train.
  await search(page, "Gajayana");
  const results = page.getByRole("dialog", { name: "Hasil pencarian" });
  await expect(results).toBeVisible({ timeout: 15_000 });
  await expect(results).toContainText(/Gajayana/);

  // Stations that have no coordinate in the data must still resolve by name
  // rather than throw or disappear.
  for (const [query, code] of [
    ["Segitiga", "STM"],
    ["Cilaku", "CIK"],
    ["Tipar", "TPR"],
  ] as const) {
    await search(page, query);
    const dialog = page.getByRole("dialog", { name: "Hasil pencarian" });
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(
      dialog.getByRole("button", { name: new RegExp(code) }).first(),
    ).toBeVisible();
  }
});

test("8. Filter popover toggles fakultatif", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  const trigger = page.getByRole("button", { name: "Filter kereta" }).filter({ visible: true }).first();
  await expect(trigger).toHaveAttribute("aria-pressed", "false");
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Filter kereta" }).filter({ visible: true });
  await expect(dialog).toBeVisible();
  const checkbox = dialog.getByRole("checkbox", { name: /Tampilkan KA fakultatif/i });
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await expect(checkbox).toBeChecked();
  await expect(trigger).toHaveAttribute("aria-pressed", "true");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("9. Tentang modal carries the full disclaimer, attribution and hash", async ({ page }) => {
  await page.goto("/");
  await ready(page);

  await page.getByRole("button", { name: "Tentang aplikasi ini" }).click();
  const dialog = page.getByRole("dialog", { name: /Tentang/i });
  await expect(dialog).toBeVisible();

  await expect(dialog).toContainText(/bukan posisi aktual/i);
  await expect(dialog).toContainText(/1 Desember 2026/);
  await expect(dialog).toContainText(/OpenStreetMap/);
  await expect(dialog).toContainText(/OpenFreeMap/);
  await expect(dialog).toContainText(/OpenRailwayMap/);
  await expect(dialog).toContainText(/Hash data/i);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // The preview banner is deliberately absent in `frontend/` (ADR 002 amendment).
  await expect(page.getByText(/Preview Gapeka 2026/)).toHaveCount(0);
});

test("10. positions are identical in two browser timezones", async ({ browser }) => {
  const read = async (timezoneId: string) => {
    const context = await browser.newContext({ timezoneId, viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.route("**/*tile*", (route) => route.abort());
    await page.route("**/*.pmtiles*", (route) => route.abort());
    // `browser.newContext()` does not inherit `use.baseURL`.
    await page.goto("http://127.0.0.1:4173/");
    await ready(page);
    // `ready()` only proves the UI mounted; the schedule arrives from the
    // worker afterwards. Scrubbing or selecting a train before it lands shows
    // "not active" and made this test race the 1.1 MB payload.
    await expect
      .poll(async () => Number(await mapCount(page, "data-train-features")), { timeout: 30_000 })
      .toBeGreaterThan(0);

    // Same instant regardless of the viewer's zone: the app uses fixed UTC+7.
    await page.getByRole("slider", { name: /Geser waktu/i }).fill("540");
    await expect(page.getByText(/Simulasi \(Estimasi\)/).filter({ visible: true }).first()).toBeVisible({
      timeout: 15_000,
    });
    await openTrain(page, "249");
    const inspector = page.getByRole("region", { name: /Inspektori KA 249/i });
    await expect(inspector).toBeVisible({ timeout: 15_000 });
    // Selecting a train renders the inspector before the worker answers for the
    // scrubbed instant, so a fractional "Tidak aktif" frame is normal. Wait for
    // the position (KA 249 is running at 09:00 WIB) and only then compare.
    await expect(inspector).toContainText(/Running/, { timeout: 15_000 });
    const text = (await inspector.innerText()).replace(/\s+/g, " ").trim();
    await context.close();
    return text;
  };

  const jakarta = await read("Asia/Jakarta");
  const newYork = await read("America/New_York");
  expect(newYork).toBe(jakarta);
});