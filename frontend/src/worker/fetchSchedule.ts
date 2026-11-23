/**
 * Fetching the exported schedule inside the worker.
 *
 * The manifest lists content-hashed filenames; using them means a new export
 * never serves a stale file from the HTTP cache. The transport is a parameter so
 * this module has no hidden dependency on `fetch`, and so the tests can assert
 * exactly which URLs are requested.
 */
import { buildSnapshot, type RawExport } from "../engine/load";
import type { ScheduleSnapshot } from "../engine/types";

export type FetchJson = (url: string) => Promise<unknown>;

const defaultFetchJson: FetchJson = async (url) => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
  return response.json() as Promise<unknown>;
};

function joinUrl(base: string, name: string): string {
  return `${base.replace(/\/+$/, "")}/${name}`;
}

/**
 * Load and build the snapshot from `baseUrl`.
 *
 * `manifest.json` is always fetched first and is never hash-suffixed: it is the
 * document that names the hashed files.
 */
export async function fetchSnapshot(
  baseUrl: string,
  fetchJson: FetchJson = defaultFetchJson,
): Promise<ScheduleSnapshot> {
  const manifestUrl = joinUrl(baseUrl, "manifest.json");

  let manifest: RawExport["manifest"];
  try {
    manifest = (await fetchJson(manifestUrl)) as RawExport["manifest"];
  } catch (error) {
    throw new Error(`cannot load ${manifestUrl}: ${String(error)}`);
  }

  const files = manifest.files ?? {};
  const resolve = (name: "stations" | "segments" | "trips"): string =>
    joinUrl(baseUrl, files[name] ?? `${name}.json`);

  const [stations, segments, trips] = await Promise.all([
    fetchJson(resolve("stations")) as Promise<RawExport["stations"]>,
    fetchJson(resolve("segments")) as Promise<RawExport["segments"]>,
    fetchJson(resolve("trips")) as Promise<RawExport["trips"]>,
  ]);

  return buildSnapshot({ manifest, stations, segments, trips });
}