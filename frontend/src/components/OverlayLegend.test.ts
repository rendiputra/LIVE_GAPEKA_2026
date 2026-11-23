/**
 * OverlayLegend content.
 *
 * The legend only exists when an OpenRailwayMap overlay is active. Its rows are
 * the only place the overlay's legend is defined as data, so both the component
 * and the tests read the same table.
 */
import { describe, expect, it } from "vitest";
import { isOverlayActive, LEGEND_ROWS, legendSummary } from "./OverlayLegend";

describe("isOverlayActive", () => {
  it("is false for the default overlay", () => {
    expect(isOverlayActive("default")).toBe(false);
  });

  it("is true for both ORM overlays", () => {
    expect(isOverlayActive("infrastruktur")).toBe(true);
    expect(isOverlayActive("maxspeed")).toBe(true);
  });
});

describe("legend rows", () => {
  it("explains the main track", () => {
    const mainTrack = LEGEND_ROWS.find((row) => row.id === "main-track");
    expect(mainTrack).toBeDefined();
    expect(mainTrack!.label).toContain("Rel utama");
  });

  it("explains sidings and yard", () => {
    expect(LEGEND_ROWS.some((row) => row.label.includes("siding"))).toBe(true);
    expect(LEGEND_ROWS.some((row) => row.label.includes("emplacement"))).toBe(true);
  });

  it("distinguishes switch vs. crossover", () => {
    const kinds = LEGEND_ROWS.map((row) => row.label);
    expect(kinds.some((label) => label.includes("wissel"))).toBe(true);
    expect(kinds.some((label) => label.includes("kruiswissel"))).toBe(true);
  });

  it("keeps OSM/ORM community provenance distinct from Gapeka printed speeds", () => {
    const summary = legendSummary("infrastruktur");
    expect(summary).toContain("komunitas");
    expect(summary).toContain("OpenStreetMap");
    expect(summary).toContain("Gapeka");
    expect(summary.toLowerCase()).toContain("maxspeed");
  });

  it("names the max speed row differently from a Gapeka speed", () => {
    const maxSpeed = LEGEND_ROWS.find((row) => row.id === "maxspeed");
    expect(maxSpeed).toBeDefined();
    expect(maxSpeed!.label).toContain("maks. kecepatan teknis");
    // The row must explicitly NOT be Gapeka data.
    expect(maxSpeed!.label).toContain("bukan Gapeka");
    expect(maxSpeed!.source).toBe("openrailwaymap");
  });

  it("marks unverified symbols as community-provided", () => {
    const every = LEGEND_ROWS.every((row) => row.source === "openrailwaymap");
    expect(every).toBe(true);
  });
});