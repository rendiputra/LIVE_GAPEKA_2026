/**
 * The OpenRailwayMap mini-legend.
 *
 * `Infrastruktur` and `Max Speed` are different renderings of different OSM
 * tags, so they must not share one row list: showing "wissel" under a Max Speed
 * heading is factually wrong. Each overlay gets its own table, and every row is
 * community data, never Gapeka data.
 */
import { describe, expect, it } from "vitest";
import {
  INFRA_ROWS,
  SPEED_ROWS,
  isOverlayActive,
  legendRows,
  legendSummary,
} from "./OverlayLegend";

describe("isOverlayActive", () => {
  it("is false for the default overlay", () => {
    expect(isOverlayActive("default")).toBe(false);
  });

  it("is true for both ORM overlays", () => {
    expect(isOverlayActive("infrastruktur")).toBe(true);
    expect(isOverlayActive("maxspeed")).toBe(true);
  });
});

describe("legendRows", () => {
  it("gives Infrastruktur its own infrastructure rows", () => {
    const rows = legendRows("infrastruktur");
    expect(rows).toBe(INFRA_ROWS);
    const labels = rows.map((row) => row.label);
    expect(labels).toContain("Rel utama (main line)");
    expect(labels.some((label) => label.includes("Siding"))).toBe(true);
    expect(labels.some((label) => label.includes("Wesel"))).toBe(true);
  });

  it("gives Max Speed speed bands, never infrastructure rows", () => {
    const rows = legendRows("maxspeed");
    expect(rows).toBe(SPEED_ROWS);

    const text = rows.map((row) => row.label).join(" ");
    expect(text).toContain("80–120");
    expect(text).toContain("km/j");
    expect(text).toContain("> 200");
    // The QA bug: infrastructure vocabulary under a Max Speed heading.
    expect(text).not.toContain("wissel");
    expect(text).not.toContain("kruiswissel");
    expect(text).not.toContain("Rel utama");
    expect(text).not.toContain("yard");
  });

  it("covers the full ORM speed ramp plus the untagged case", () => {
    expect(SPEED_ROWS.map((row) => row.label)).toEqual([
      "< 40 km/j",
      "40–60 km/j",
      "60–80 km/j",
      "80–120 km/j",
      "120–160 km/j",
      "160–200 km/j",
      "> 200 km/j",
      "Abu-abu: belum ada tag maxspeed",
    ]);
  });

  it("has no duplicate row ids", () => {
    for (const rows of [INFRA_ROWS, SPEED_ROWS]) {
      const ids = rows.map((row) => row.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });

  it("keeps the two legends disjoint", () => {
    const infra = new Set(INFRA_ROWS.map((row) => row.id));
    for (const row of SPEED_ROWS) expect(infra.has(row.id)).toBe(false);
  });
});

describe("legendSummary", () => {
  it("says the data is community OSM/OpenRailwayMap data", () => {
    for (const overlay of ["infrastruktur", "maxspeed"] as const) {
      const summary = legendSummary(overlay);
      expect(summary).toContain("komunitas");
      expect(summary).toContain("OpenStreetMap");
      expect(summary).toContain("OpenRailwayMap");
    }
  });

  it("distinguishes the overlay speed from the printed Gapeka speed", () => {
    const summary = legendSummary("maxspeed");
    expect(summary).toContain("Bukan data Gapeka");
    expect(summary).toContain("Kecepatan");
  });

  it("is empty when no overlay is active", () => {
    expect(legendSummary("default")).toBe("");
  });
});