// Accessibility audit (Turn 3b): axe over the production build, in the states
// that matter — default load, About modal, Layers popover, Filter popover, and
// a selected train. Report-only collection lives here; the assertions are in
// a11y.spec.ts.
//
// Run: node e2e/a11y-audit.mjs [url]

import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REVIEW = resolve(HERE, "../../data/review");
const URL_UNDER_TEST = process.argv[2] ?? "http://127.0.0.1:4174/";
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Every violation, flattened to what a human needs to fix it. */
function summarise(violations) {
  return violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    nodes: violation.nodes.map((node) => ({
      target: node.target.join(" "),
      html: (node.html ?? "").slice(0, 160),
      failure: (node.failureSummary ?? "").slice(0, 240),
    })),
  }));
}

async function scan(page, label) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  return {
    state: label,
    violations: results.violations.length,
    serious_or_critical: serious.length,
    detail: summarise(results.violations),
  };
}

async function main() {
  mkdirSync(REVIEW, { recursive: true });
  const browser = await chromium.launch();
  // axe-core/playwright injects its script through a new page, which requires a
  // context; `browser.newPage()` cannot be reused for that.
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  // Tiles are external; blocking keeps the audit about our own DOM.
  await page.route("**/*tile*", (route) => route.abort());
  await page.route("**/*.pmtiles*", (route) => route.abort());

  await page.goto(URL_UNDER_TEST);
  // The readiness signal is the Live status pill: it only exists once the
  // schedule has loaded and the snapshot is real.
  await page.locator("text=Live (Estimasi)").first().waitFor({ state: "visible", timeout: 40_000 });

  const states = [];
  states.push(await scan(page, "default"));

  // About modal
  await page.getByRole("button", { name: "Tentang aplikasi ini" }).click();
  await page.getByRole("dialog", { name: /tentang/i }).waitFor();
  states.push(await scan(page, "about-modal"));
  await page.keyboard.press("Escape");
  await page.getByRole("dialog", { name: /tentang/i }).waitFor({ state: "detached" });

  // Layers popover
  await page.getByRole("button", { name: /lapisan peta|layer/i }).click();
  await page.getByRole("dialog", { name: /lapisan peta/i }).waitFor();
  states.push(await scan(page, "layers-popover"));
  await page.keyboard.press("Escape");
  await page.getByRole("dialog", { name: /lapisan peta/i }).waitFor({ state: "detached" });

  // Filter popover
  await page.getByRole("button", { name: /filter kereta/i }).click();
  await page.getByRole("dialog", { name: /filter kereta/i }).waitFor();
  states.push(await scan(page, "filter-popover"));
  await page.keyboard.press("Escape");

  // A selected train (the inspector, expanded)
  await page.getByRole("searchbox").fill("249");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: /KA 249/i }).first().click();
  await page.waitForTimeout(400);
  states.push(await scan(page, "train-inspector"));

  // Badges/pills: KA 265 carries the "estimasi kasar" badge (flags bit 0), so
  // this state is where badge contrast is actually exercised.
  await page.getByRole("searchbox").fill("265");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: /KA 265/i }).first().click();
  await page.waitForTimeout(400);
  states.push(await scan(page, "coarse-train-badges"));

  await browser.close();

  const totalSerious = states.reduce((sum, state) => sum + state.serious_or_critical, 0);
  const payload = {
    url: URL_UNDER_TEST,
    tags: TAGS,
    states,
    total_violations: states.reduce((sum, state) => sum + state.violations, 0),
    total_serious_or_critical: totalSerious,
  };
  writeFileSync(
    resolve(REVIEW, "frontend_axe.json"),
    JSON.stringify(payload, null, 2) + "\n",
  );

  for (const state of states) {
    console.log(
      `${state.state}: ${state.violations} violation(s), ` +
        `${state.serious_or_critical} serious/critical`,
    );
    for (const item of state.detail) {
      console.log(`   [${item.impact}] ${item.id}: ${item.help}`);
      for (const node of item.nodes.slice(0, 3)) {
        console.log(`      ${node.target}`);
      }
    }
  }
  console.log(`TOTAL serious/critical: ${totalSerious}`);
  process.exitCode = totalSerious === 0 ? 0 : 1;
}

await main();
