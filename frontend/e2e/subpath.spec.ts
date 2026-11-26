// Sub-path deployment check (Turn 3b).
//
// The bundle is built with `base: "./"`, so it must work when the whole site is
// served from a sub-path rather than the server root. That includes the Web
// Worker: its script URL is resolved from `import.meta.url`, and the schedule is
// fetched from `import.meta.env.BASE_URL`. If either resolves against the server
// root instead of the page, the app loads but never becomes ready — which is
// exactly the failure this test exists to catch.

import { expect, test } from "@playwright/test";

const SUBPATH_URL = "http://127.0.0.1:4175/sub/";

test("loads and becomes ready when served from a sub-path", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  // External tiles and fonts are irrelevant here; keep the test offline.
  await page.route("**/*tile*", (route) => route.abort());
  await page.route("**/*.pmtiles*", (route) => route.abort());

  await page.goto(SUBPATH_URL);

  // The Live pill only renders once the worker has loaded the schedule, so this
  // proves the worker script AND the data fetch both resolved correctly.
  await expect(page.getByText(/Live \(Estimasi\)/).first()).toBeVisible({
    timeout: 40_000,
  });

  // Assets must come from the sub-path, not the root.
  const scripts = await page.locator("script[src]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("src") ?? ""),
  );
  expect(scripts.length).toBeGreaterThan(0);
  for (const src of scripts) {
    expect(src.startsWith("./assets/") || src.startsWith("assets/")).toBe(true);
  }

  expect(errors).toEqual([]);
});