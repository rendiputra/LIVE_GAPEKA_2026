/**
 * The worker fetches the exported JSON off the main thread. The transport is
 * injected so the cache-busting rules are testable without a network.
 */
import { describe, expect, it } from "vitest";
import { fetchSnapshot } from "./fetchSchedule";
import { readExportedBundle } from "../engine/testUtils";

describe("fetchSnapshot", () => {
  it("prefers the content-hashed filenames the manifest lists", async () => {
    const raw = await readExportedBundle();
    const requested: string[] = [];
    const fetchJson = async (url: string): Promise<unknown> => {
      requested.push(url);
      if (url.endsWith("manifest.json")) return raw.manifest;
      if (url.includes("stations.")) return raw.stations;
      if (url.includes("segments.")) return raw.segments;
      if (url.includes("trips.")) return raw.trips;
      throw new Error(`unexpected url ${url}`);
    };

    const snapshot = await fetchSnapshot("/data", fetchJson);

    expect(requested[0]).toBe("/data/manifest.json");
    expect(requested).toContain(`/data/${raw.manifest.files!.stations}`);
    expect(snapshot.versionName).toBe("Gapeka 2026");
    expect(snapshot.trips).toHaveLength(625);
  });

  it("falls back to the plain filenames when the manifest has no file list", async () => {
    const raw = await readExportedBundle();
    const { files: _files, ...manifestWithoutFiles } = raw.manifest;
    const requested: string[] = [];
    const fetchJson = async (url: string): Promise<unknown> => {
      requested.push(url);
      if (url.endsWith("manifest.json")) return manifestWithoutFiles;
      if (url.endsWith("stations.json")) return raw.stations;
      if (url.endsWith("segments.json")) return raw.segments;
      if (url.endsWith("trips.json")) return raw.trips;
      throw new Error(`unexpected url ${url}`);
    };

    await fetchSnapshot("/data/", fetchJson);

    expect(requested).toContain("/data/stations.json");
    expect(requested.every((url) => !url.endsWith("//stations.json"))).toBe(true);
  });

  it("surfaces a load failure with the URL that failed", async () => {
    const fetchJson = async (url: string): Promise<unknown> => {
      throw new Error(`404 ${url}`);
    };
    await expect(fetchSnapshot("/data", fetchJson)).rejects.toThrow(/\/data\/manifest\.json/);
  });
});