// Collect the Turn 3b evidence into ONE artefact the report can quote.
//
// This script runs nothing and touches no network: it only reads the outputs
// that the real gates already wrote, so every number in
// `docs/frontend_revamp_report.md` has a machine-produced source:
//
//   data/review/frontend_vitest.json     `npx vitest run --reporter=json`
//   data/review/frontend_e2e.json        `PLAYWRIGHT_JSON_OUTPUT_NAME=… npx playwright test --reporter=json`
//   data/review/python_junit.xml         `uv run pytest --junitxml=…`
//   data/review/frontend_axe.json        `node e2e/a11y-audit.mjs`
//   data/review/frontend_lighthouse.json `make frontend-lighthouse`
//   data/review/frontend_export.json     `make export-frontend`
//   data/review/frontend_reproduce.txt   `make reproduce | tee …`
//   engine/parity_frames.json            `make parity`
//
// Usage: node e2e/verification.mjs

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const read = (relative) => readFileSync(resolve(REPO, relative), "utf8");
const json = (relative) => JSON.parse(read(relative));

const vitest = json("data/review/frontend_vitest.json");
const e2e = json("data/review/frontend_e2e.json");
const axe = json("data/review/frontend_axe.json");
const lighthouse = json("data/review/frontend_lighthouse.json");
const exported = json("data/review/frontend_export.json");
const parityFixture = json("engine/parity_frames.json");
const reproduce = read("data/review/frontend_reproduce.txt");

// JUnit is the only XML input; a regex is enough for four attributes.
const junit = read("data/review/python_junit.xml").match(/<testsuite\b[^>]*>/)?.[0] ?? "";
const junitAttr = (name) => Number(junit.match(new RegExp(`${name}="(\\d+)"`))?.[1] ?? NaN);

// Vitest's JSON report nests assertions under testResults[].assertionResults.
const parityTest = vitest.testResults
  .flatMap((file) => file.assertionResults ?? [])
  .find((test) => /reproduces all 6,000 frames with zero failures/.test(test.fullName ?? test.title ?? ""));

const summary = {
  generated_by: "frontend/e2e/verification.mjs",
  note: "Reads the artefacts listed in this script; computes nothing from the PDF or the network.",
  export: {
    content_hash: exported.content_hash,
    variant: exported.variant,
    segments: exported.segments,
    stations: exported.stations,
    trips: exported.trips,
    max_day_offset: exported.max_day_offset,
    raw_bytes: exported.sizes?.total?.raw ?? null,
    gzip_bytes: exported.sizes?.total?.gzip ?? null,
  },
  vitest: {
    test_files: vitest.testResults.length,
    tests: vitest.numTotalTests,
    passed: vitest.numPassedTests,
    failed: vitest.numFailedTests,
    parity_test_status: parityTest?.status ?? null,
  },
  parity: {
    frames: parityFixture.frames?.length ?? null,
    tolerance_m: 1,
  },
  playwright: {
    expected: e2e.stats.expected,
    unexpected: e2e.stats.unexpected,
    flaky: e2e.stats.flaky,
    skipped: e2e.stats.skipped,
    duration_ms: Math.round(e2e.stats.duration),
    projects: (() => {
      const names = new Set();
      const walk = (suite) => {
        for (const spec of suite.specs ?? []) {
          for (const test of spec.tests ?? []) if (test.projectName) names.add(test.projectName);
        }
        for (const child of suite.suites ?? []) walk(child);
      };
      for (const suite of e2e.suites ?? []) walk(suite);
      return [...names].sort();
    })(),
  },
  python: {
    tests: junitAttr("tests"),
    failures: junitAttr("failures"),
    errors: junitAttr("errors"),
    skipped: junitAttr("skipped"),
    duration_s: Number(junit.match(/time="([\d.]+)"/)?.[1] ?? NaN),
  },
  axe: {
    states: axe.states.map((state) => ({ state: state.state, violations: state.violations })),
    total_violations: axe.total_violations,
    total_serious_or_critical: axe.total_serious_or_critical,
  },
  lighthouse: {
    form_factor: lighthouse.form_factor,
    viewport: lighthouse.viewport,
    tiles_blocked: lighthouse.tiles_blocked,
    scores: lighthouse.scores,
    metrics: lighthouse.metrics,
  },
  reproduce: {
    result: /^REPRODUCIBLE$/m.test(reproduce) ? "REPRODUCIBLE" : "NOT_REPRODUCIBLE",
    log: "data/review/frontend_reproduce.txt",
  },
};

const out = resolve(REPO, "data/review/frontend_verification.json");
writeFileSync(out, JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 2));
