// Entry point (B4). Static site: no server, no API. All positions are computed
// in the worker from the exported schedule; the map only renders.

import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { layers, namedFlavor } from "@protomaps/basemaps";

import {
  GLYPHS_URL,
  OSM_ATTRIBUTION,
  OSM_TILE_URL,
  PMTILES_URL,
  SPRITE_URL,
  TILE_MODE,
} from "./config";
import type { Dataset, TrainPosition } from "./engine/position";
import { decodePolyline } from "./engine/polyline";
import { defaultPolicy, type Manifest, type Policy, type TripData } from "./engine/types";

const DATA_BASE = `${import.meta.env.BASE_URL}data`;

/** Stop types are printed in English in the data; the UI speaks Indonesian. */
const STOP_LABEL: Record<string, string> = {
  stop: "Berhenti",
  pass: "Langsung",
  unknown_untimed: "Tanpa jam",
};

const CLASS_COLOUR: Record<string, string> = {
  reguler: "#1565c0",
  fakultatif: "#ef6c00",
  unknown: "#6a1b9a",
};

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`missing #${id}`);
  return element as T;
};

interface UiState {
  mode: "live" | "replay";
  date: string;
  secondsOfDay: number;
  playing: boolean;
  speed: number;
  showFakultatif: boolean;
  selectedTripId: string | null;
  selectedStation: string | null;
}

const state: UiState = {
  mode: "live",
  date: "2026-12-01",
  secondsOfDay: 9 * 3600,
  playing: false,
  speed: 60,
  showFakultatif: false,
  selectedTripId: null,
  selectedStation: null,
};

let manifest: Manifest;
let dataset: Dataset;
let stopTypes: string[] = [];
let tripsById = new Map<string, TripData>();
let stationName = new Map<string, string>();
let policy: Policy;
let worker: Worker;
let map: MapLibreMap;
let lastRendered: TrainPosition[] = [];
/** The instant the currently displayed frame was computed for. The status line
 *  must describe THIS, never the replay slider, or live mode shows replay time. */
let lastRenderedInstantMs = 0;
/** The trip whose stop list was last auto-scrolled, so a frame render does not
 *  yank the panel back while the user is reading. */
let lastAutoScrolledTripId: string | null = null;

// --- time helpers -----------------------------------------------------------

const WIB_MS = 7 * 3600 * 1000;

function instantFor(dateIso: string, secondsOfDay: number): number {
  const [year, month, day] = dateIso.split("-").map(Number);
  return Date.UTC(year, month - 1, day, 0, 0, 0) - WIB_MS + secondsOfDay * 1000;
}

/** WIB date and time for an instant, using fixed UTC+7 (no DST in Java). */
function wibClock(instantMs: number): { date: string; time: string } {
  const shifted = new Date(instantMs + WIB_MS);
  const date = shifted.toISOString().slice(0, 10);
  const seconds =
    shifted.getUTCHours() * 3600 + shifted.getUTCMinutes() * 60 + shifted.getUTCSeconds();
  return { date, time: hhmm(seconds) };
}

function hhmm(seconds: number): string {
  const h = Math.floor(seconds / 3600) % 24;
  const m = Math.floor((seconds % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// --- data -------------------------------------------------------------------

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return (await response.json()) as T;
}

function showLoadError(message: string): void {
  const loading = document.getElementById("loading");
  const error = document.getElementById("load-error");
  if (loading) loading.hidden = true;
  if (error) {
    error.textContent = message;
    error.hidden = false;
  }
}

async function loadData(): Promise<void> {
  manifest = await fetchJson<Manifest>(`${DATA_BASE}/manifest.json`);
  const stations = await fetchJson<{ stations: Dataset["stations"] }>(
    `${DATA_BASE}/stations.json`,
  );
  const segments = await fetchJson<{ segments: Dataset["segments"] }>(
    `${DATA_BASE}/segments.json`,
  );
  const trips = await fetchJson<{ trips: TripData[]; stop_types: string[] }>(
    `${DATA_BASE}/trips.json`,
  );

  // F6: the UI does NOT call prepare(). That decodes all 391 polylines and
  // builds every trip, which the worker already does — doing it twice on the
  // main thread was most of the 1.8 s total blocking time. The UI only needs the
  // station list and the raw segment records.
  dataset = {
    manifest,
    stations: stations.stations,
    stationByCode: new Map(stations.stations.map((station) => [station.code, station])),
    segments: segments.segments,
    trips: [],
  };
  tripsById = new Map(trips.trips.map((trip) => [trip.trip_id, trip]));
  stopTypes = trips.stop_types;
  stationName = new Map(
    stations.stations.map((station) => [
      station.code,
      station.disambiguator
        ? `${station.official_name} (${station.disambiguator})`
        : station.official_name,
    ]),
  );
  policy = defaultPolicy(manifest);
  policy.showFakultatif = state.showFakultatif;

  const loading = document.getElementById("loading");
  if (loading) loading.hidden = true;
}

// --- map --------------------------------------------------------------------

function basemapStyle(): maplibregl.StyleSpecification {
  if (TILE_MODE === "osm") {
    // Development only; the production build refuses this mode.
    return {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: [OSM_TILE_URL],
          tileSize: 256,
          attribution: OSM_ATTRIBUTION,
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    };
  }

  // Self-hosted Protomaps vector tiles. `lang: "id"` asks the theme for
  // Indonesian labels where a name:id tag exists.
  const mapLayers = layers("protomaps", namedFlavor("light"), { lang: "id" });
  return {
    version: 8,
    glyphs: GLYPHS_URL,
    sprite: SPRITE_URL,
    sources: {
      protomaps: {
        type: "vector",
        url: PMTILES_URL,
        attribution: OSM_ATTRIBUTION,
      },
    },
    layers: mapLayers as maplibregl.LayerSpecification[],
  };
}

function buildMap(): void {
  if (TILE_MODE === "pmtiles") {
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
  }

  map = new maplibregl.Map({
    container: "map",
    style: basemapStyle(),
    center: [110.4, -7.2],
    // z6-7 is inherently coarse in the Protomaps theme (Natural Earth coastline,
    // about one locality per tile). Starting a little closer shows real detail
    // and city labels without downloading extra zoom levels.
    zoom: 7.2,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  // Exposed for the Playwright checks only; the UI never reads it.
  (window as unknown as { __gapekaMap?: MapLibreMap }).__gapekaMap = map;

  map.on("load", () => {
    map.addImage("arrow", arrowImage());
    map.addSource("trains", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer({
      id: "trains-dot",
      type: "circle",
      source: "trains",
      paint: {
        "circle-radius": 6,
        "circle-color": ["get", "colour"],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "trains-arrow",
      type: "symbol",
      source: "trains",
      layout: {
        "icon-image": "arrow",
        "icon-rotate": ["get", "bearing"],
        "icon-rotation-alignment": "map",
        "icon-size": 0.6,
        "icon-allow-overlap": true,
      },
    });

    // F3/F6: the exported rail network as a subtle background layer. Building it
    // decodes 391 polylines, so it is DEFERRED to idle time: it must not compete
    // with the first paint (that was long-task blocking time).
    map.addSource("rail", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer(
      {
        id: "rail-line",
        type: "line",
        source: "rail",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#5b6472",
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.4, 10, 1.2, 14, 2],
          "line-opacity": 0.55,
        },
      },
      // Under the train markers, above the basemap.
      "trains-dot",
    );
    const buildRail = () => {
      const source = map.getSource("rail") as maplibregl.GeoJSONSource | undefined;
      source?.setData(railGeoJson());
    };
    const idle = (
      window as Window & {
        requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      }
    ).requestIdleCallback;
    if (idle) idle(buildRail, { timeout: 2000 });
    else setTimeout(buildRail, 300);

    // F3: the selected train's route, highlighted.
    map.addSource("route", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addLayer(
      {
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#b00020",
          "line-width": ["interpolate", ["linear"], ["zoom"], 6, 2, 10, 4, 14, 6],
          "line-opacity": 0.9,
        },
      },
      "trains-dot",
    );

    map.on("click", "trains-dot", (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      selectTrip(String(feature.properties?.tripId ?? ""));
    });
    map.on("mouseenter", "trains-dot", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "trains-dot", () => {
      map.getCanvas().style.cursor = "";
    });
  });
}

/** Every exported segment as one MultiLineString, for the background rail layer. */
function railGeoJson(): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const segment of dataset.segments) {
    const points = decodePolyline(segment.polyline).map(([lat, lon]) => [lon, lat]);
    if (points.length < 2) continue;
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: points },
      properties: { from: segment.from, to: segment.to, quality: segment.quality },
    });
  }
  return { type: "FeatureCollection", features };
}

/** Highlight one trip's full route, oriented as the train runs it. */
function highlightRoute(tripId: string | null): void {
  const source = map.getSource("route") as maplibregl.GeoJSONSource | undefined;
  if (!source) return;
  if (!tripId) {
    source.setData({ type: "FeatureCollection", features: [] });
    return;
  }
  const trip = tripsById.get(tripId);
  if (!trip) {
    source.setData({ type: "FeatureCollection", features: [] });
    return;
  }
  const coordinates: Array<[number, number]> = [];
  for (let index = 0; index < trip.segment_ids.length; index += 1) {
    const segment = dataset.segments[trip.segment_ids[index]];
    const points = decodePolyline(segment.polyline).map(
      ([lat, lon]) => [lon, lat] as [number, number],
    );
    const ordered = trip.reversed[index] === 1 ? [...points].reverse() : points;
    for (const point of ordered) {
      if (coordinates.length === 0) {
        coordinates.push(point);
        continue;
      }
      const last = coordinates[coordinates.length - 1];
      if (last[0] !== point[0] || last[1] !== point[1]) coordinates.push(point);
    }
  }
  source.setData({
    type: "FeatureCollection",
    features: coordinates.length > 1
      ? [
          {
            type: "Feature",
            geometry: { type: "LineString", coordinates },
            properties: { tripId },
          },
        ]
      : [],
  });
}

function arrowImage(): ImageData {
  const size = 32;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d unavailable");
  ctx.fillStyle = "#0f172a";
  ctx.beginPath();
  ctx.moveTo(size / 2, 4);
  ctx.lineTo(size - 8, size - 6);
  ctx.lineTo(size / 2, size - 12);
  ctx.lineTo(8, size - 6);
  ctx.closePath();
  ctx.fill();
  return ctx.getImageData(0, 0, size, size);
}

// --- rendering --------------------------------------------------------------

function renderPositions(positions: TrainPosition[]): void {
  lastRendered = positions;
  const source = map.getSource("trains") as maplibregl.GeoJSONSource | undefined;
  if (!source) return;
  source.setData({
    type: "FeatureCollection",
    features: positions.map((position) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [position.lon, position.lat] },
      properties: {
        tripId: position.tripId,
        bearing: position.bearing,
        colour: CLASS_COLOUR[position.serviceClass] ?? CLASS_COLOUR.unknown,
      },
    })),
  });
  const shown = wibClock(lastRenderedInstantMs);
  $("status").textContent =
    `${positions.length} KA aktif · ${shown.time} WIB · ${shown.date}`;
}

function panelHtml(position: TrainPosition): string {
  const trip = tripsById.get(position.tripId);
  const badges: string[] = [];
  if (position.coarse) badges.push('<span class="badge coarse">estimasi kasar</span>');
  if (position.serviceClass === "fakultatif") badges.push('<span class="badge">fakultatif</span>');

  const stops = trip
    ? trip.waypoints.code.map((codeIndex, i) => {
        const station = dataset.stations[codeIndex];
        const code = station?.code ?? "?";
        const arrive = trip.waypoints.arrive[i];
        const depart = trip.waypoints.depart[i];
        const printed = arrive >= 0 ? arrive : depart;
        const clock = printed >= 0 ? hhmm(((printed % 86400) + 86400) % 86400) : "—";
        const bypassed = (trip.waypoints.bypassed?.[i] ?? 0) === 1;
        const isCurrent =
          !bypassed &&
          (Math.abs(trip.waypoints.s_m[i] - position.sM) < 1 ||
            code === position.fromCode ||
            code === position.toCode);
        // A bypassed row has no coordinate, so its position is an estimate
        // between its neighbours. Say so rather than pretending it is exact.
        const note = bypassed ? ' <span class="t">(tanpa koordinat)</span>' : "";
        return `<li class="${isCurrent ? "current" : ""}${bypassed ? " bypassed" : ""}">
          <span>${stationName.get(code) ?? code}${note}</span>
          <span class="t">${clock}</span>
          <span class="t">${
            STOP_LABEL[stopTypes[trip.waypoints.stop_type[i]] ?? ""] ?? ""
          }</span>
        </li>`;
      })
    : [];

  return `
    <h2 class="train-title">KA ${position.trainNo}${trip?.name ? ` — ${trip.name}` : ""}</h2>
    <p class="train-meta">
      ${trip?.relation ? `${trip.relation} · ` : ""}${badges.join("")}
    </p>
    <p class="train-meta">
      ${position.status === "at_station" ? "Berhenti di" : "Menuju"}
      <b>${stationName.get(position.toCode) ?? position.toCode}</b>
      · ${Math.round(position.speedKmh)} km/jam
    </p>
    <p class="train-meta">
      ${position.nextStopCode
        ? `Stasiun berikutnya <b>${stationName.get(position.nextStopCode) ?? position.nextStopCode}</b> pukul ${position.nextStopTime ?? "—"}`
        : "Tidak ada stasiun berikutnya"}
    </p>
    <ul class="stoplist">${stops.join("")}</ul>
  `;
}

function renderPanel(): void {
  const panel = $("panel");
  if (state.selectedStation) {
    renderStationBoard(state.selectedStation);
    return;
  }
  if (!state.selectedTripId) {
    panel.innerHTML =
      '<p class="empty">Ketuk penanda kereta untuk melihat jadwalnya, atau cari nomor KA di atas.</p>';
    return;
  }
  const position = lastRendered.find((p) => p.tripId === state.selectedTripId);
  if (!position) {
    const trip = tripsById.get(state.selectedTripId);
    const hiddenByPolicy =
      trip && trip.service_class !== "reguler" && !policy.showFakultatif;
    panel.innerHTML =
      `<h2 class="train-title">KA ${trip?.train_no ?? ""}${
        trip?.name ? ` — ${trip.name}` : ""
      }</h2>` +
      `<p class="empty">${
        hiddenByPolicy
          ? "KA fakultatif disembunyikan. Aktifkan “Tampilkan KA fakultatif”."
          : "KA ini tidak aktif pada waktu yang dipilih."
      }</p>`;
    return;
  }
  panel.innerHTML = panelHtml(position);
  // Only on a NEW selection: re-scrolling every frame would fight the user, who
  // may be reading a different part of the list.
  if (lastAutoScrolledTripId !== state.selectedTripId) {
    lastAutoScrolledTripId = state.selectedTripId;
    scrollCurrentStopIntoView(panel);
  }
}

/** F4: a long stop list must open at the train's current position. */
function scrollCurrentStopIntoView(panel: HTMLElement): void {
  const current = panel.querySelector("li.current");
  if (!current) return;
  // `block: "center"` keeps context above and below; `nearest` avoids moving
  // the page when the panel is already visible.
  current.scrollIntoView({ block: "center", behavior: "auto" });
}

function selectTrip(tripId: string): void {
  state.selectedTripId = tripId;
  state.selectedStation = null;
  highlightRoute(tripId);
  renderPanel();
  const position = lastRendered.find((p) => p.tripId === tripId);
  if (position) map.easeTo({ center: [position.lon, position.lat], zoom: Math.max(map.getZoom(), 8) });
}

// --- station board ----------------------------------------------------------

function renderStationBoard(code: string): void {
  const panel = $("panel");
  const windowStart = state.secondsOfDay;
  const windowEnd = windowStart + 3 * 3600;
  const rows: Array<{ trainNo: string; name: string; time: number; kind: string }> = [];

  for (const trip of tripsById.values()) {
    const columns = trip.waypoints;
    for (let i = 0; i < columns.code.length; i += 1) {
      const station = dataset.stations[columns.code[i]];
      if (!station || station.code !== code) continue;
      const arrive = columns.arrive[i];
      const depart = columns.depart[i];
      const time = arrive >= 0 ? arrive : depart;
      if (time < 0) continue;
      const secondOfDay = ((time % 86400) + 86400) % 86400;
      for (const dayOffset of [0, 86400]) {
        const absolute = secondOfDay + dayOffset;
        if (absolute < windowStart || absolute > windowEnd) continue;
        rows.push({
          trainNo: trip.train_no,
          name: trip.name,
          time: absolute,
          kind: arrive >= 0 && depart >= 0 && arrive !== depart ? "berhenti" : "lewat",
        });
      }
    }
  }

  rows.sort((a, b) => a.time - b.time);
  const list = rows
    .slice(0, 10)
    .map(
      (row) =>
        `<li><span>KA ${row.trainNo}${row.name ? ` — ${row.name}` : ""}</span>` +
        `<span class="t">${hhmm(row.time)}</span><span class="t">${row.kind}</span></li>`,
    )
    .join("");

  panel.innerHTML =
    `<h2 class="train-title">${stationName.get(code) ?? code}</h2>` +
    `<p class="train-meta">10 KA berikutnya dalam 3 jam ke depan</p>` +
    `<ul class="stoplist">${list || '<li><span>Tidak ada KA</span><span></span><span></span></li>'}</ul>`;
  map.easeTo({
    center: [
      dataset.stations.find((s) => s.code === code)?.lon ?? 110.4,
      dataset.stations.find((s) => s.code === code)?.lat ?? -7.2,
    ],
    zoom: 10,
  });
}

// --- search -----------------------------------------------------------------

/** F6: 3,000 <option> elements at startup was a long task. Built once, on first
 *  focus, and capped: the search matches on input anyway, so the list is a hint. */
let searchIndexBuilt = false;
const SEARCH_HINT_LIMIT = 500;

function buildSearchIndex(): void {
  if (searchIndexBuilt) return;
  searchIndexBuilt = true;
  const list = $("search-list");
  const options: string[] = [];
  for (const trip of tripsById.values()) {
    options.push(`KA ${trip.train_no}${trip.name ? ` ${trip.name}` : ""}`);
  }
  for (const station of dataset.stations) {
    if (stationName.has(station.code)) options.push(stationName.get(station.code) as string);
  }
  options.sort();
  list.innerHTML = options
    .slice(0, SEARCH_HINT_LIMIT)
    .map((option) => `<option value="${option.replace(/"/g, "&quot;")}"></option>`)
    .join("");
}

function handleSearch(query: string): void {
  const value = query.trim().toLowerCase();
  if (!value) return;

  const trainMatch = value.match(/^(?:ka\s*)?([a-z0-9]+f?)$/i);
  if (trainMatch) {
    const wanted = trainMatch[1].toUpperCase();
    const trip = [...tripsById.values()].find(
      (candidate) => candidate.train_no.toUpperCase() === wanted,
    );
    if (trip) {
      selectTrip(trip.trip_id);
      return;
    }
  }

  const station = dataset.stations.find((candidate) => {
    const name = (stationName.get(candidate.code) ?? "").toLowerCase();
    return name === value || name.includes(value);
  });
  if (station) {
    state.selectedStation = station.code;
    state.selectedTripId = null;
    highlightRoute(null);
    renderPanel();
    return;
  }

  const byName = [...tripsById.values()].find((candidate) =>
    (candidate.name ?? "").toLowerCase().includes(value),
  );
  if (byName) {
    selectTrip(byName.trip_id);
    return;
  }
  $("status").textContent = `Tidak ditemukan: ${query}`;
  state.selectedTripId = null;
  state.selectedStation = null;
  $("panel").innerHTML =
    `<p class="empty">Tidak ada KA atau stasiun yang cocok dengan “${query}”. ` +
    "Coba nomor KA (mis. 249) atau nama stasiun (mis. Gambir).</p>";
}

// --- worker -----------------------------------------------------------------

let requestId = 0;
const pending = new Map<number, (positions: TrainPosition[]) => void>();

function startWorker(): void {
  worker = new Worker(new URL("./worker/positions.worker.ts", import.meta.url), {
    type: "module",
  });
  worker.onmessage = (event: MessageEvent) => {
    const message = event.data as
      | { type: "ready" }
      | { type: "result"; id: number; positions: TrainPosition[] }
      | { type: "error"; error: string; id?: number };
    if (message.type === "ready") {
      $("status").textContent = "Data siap.";
      requestFrame();
      return;
    }
    if (message.type === "error") {
      $("status").textContent = `Galat: ${message.error}`;
      return;
    }
    const resolve = pending.get(message.id);
    if (resolve) {
      pending.delete(message.id);
      resolve(message.positions);
    }
  };
  // Absolute URL: inside a worker a relative fetch resolves against the WORKER
  // script, not the page, which silently returned index.html.
  worker.postMessage({ type: "init", base: new URL(DATA_BASE, window.location.href).href });
}

function workerPositions(instantMs: number): Promise<TrainPosition[]> {
  const id = ++requestId;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    worker.postMessage({ type: "query", id, instantMs, policy });
  });
}

// --- frame loop -------------------------------------------------------------

function currentInstant(): number {
  if (state.mode === "live") return Date.now();
  return instantFor(state.date, state.secondsOfDay);
}

let frameInFlight = false;
let frameDirty = false;

declare global {
  interface Window {
    __gapekaBench?: { frameMs: number; trains: number };
  }
}

async function requestFrame(): Promise<void> {
  // The worker is created after the controls are wired, and it may fail to
  // construct; asking for a frame before then must be a no-op, not a crash.
  // startWorker() requests the first frame once the data is ready.
  if (!worker) return;
  // Coalesce, but never DROP the last request: a slider drag or a clock tick
  // that arrives while a frame is in flight must still be rendered.
  if (frameInFlight) {
    frameDirty = true;
    return;
  }
  frameInFlight = true;
  try {
    do {
      frameDirty = false;
      const instant = currentInstant();
      const started = performance.now();
      const positions = await workerPositions(instant);
      // Record the instant this frame describes BEFORE rendering, so the status
      // line can never show a different clock from the positions on the map.
      lastRenderedInstantMs = instant;
      renderPositions(positions);
      renderPanel();
      // Exposed for the Playwright benchmark; not used by the UI.
      window.__gapekaBench = {
        frameMs: performance.now() - started,
        trains: positions.length,
      };
    } while (frameDirty);
  } finally {
    frameInFlight = false;
  }
}

function tick(): void {
  updateBanner();
  if (state.mode === "live") {
    requestFrame();
    window.setTimeout(tick, 1000);
    return;
  }
  if (state.playing) {
    state.secondsOfDay = (state.secondsOfDay + state.speed) % 86400;
    $("time").setAttribute("value", String(state.secondsOfDay));
    ($("time") as HTMLInputElement).value = String(state.secondsOfDay);
    $("clock").textContent = hhmm(state.secondsOfDay);
  setMode(state.mode);
    requestFrame();
  }
  window.setTimeout(tick, 200);
}

// --- wiring -----------------------------------------------------------------

/** Keep the replay inputs and the clock in step with the state. */
function syncReplayInputs(): void {
  ($("date") as HTMLInputElement).value = state.date;
  ($("time") as HTMLInputElement).value = String(state.secondsOfDay);
  $("clock").textContent = hhmm(state.secondsOfDay);
  setMode(state.mode);
}

/** Switching mode also shows/hides the replay controls, so live and replay can
 *  never be confused. */
function setMode(mode: "live" | "replay"): void {
  state.mode = mode;
  $("mode-live").setAttribute("aria-checked", String(mode === "live"));
  $("mode-replay").setAttribute("aria-checked", String(mode === "replay"));
  ($("replay-controls") as HTMLElement).hidden = mode === "live";
  if (mode === "live") {
    // Leaving replay stops playback; otherwise the slider keeps advancing
    // invisibly and the user cannot tell which clock they are looking at.
    state.playing = false;
    $("play").setAttribute("aria-pressed", "false");
    $("play").textContent = "Putar";
  } else {
    syncReplayInputs();
  }
  requestFrame();
}

function wireControls(): void {
  $("mode-live").addEventListener("click", () => setMode("live"));
  $("mode-replay").addEventListener("click", () => setMode("replay"));

  ($("date") as HTMLInputElement).addEventListener("change", (event) => {
    state.date = (event.target as HTMLInputElement).value || "2026-12-01";
    requestFrame();
  });

  ($("time") as HTMLInputElement).addEventListener("input", (event) => {
    state.secondsOfDay = Number((event.target as HTMLInputElement).value);
    $("clock").textContent = hhmm(state.secondsOfDay);
  setMode(state.mode);
    requestFrame();
  });

  $("play").addEventListener("click", () => {
    state.playing = !state.playing;
    $("play").setAttribute("aria-pressed", String(state.playing));
    $("play").textContent = state.playing ? "Jeda" : "Putar";
  });

  ($("speed") as HTMLSelectElement).addEventListener("change", (event) => {
    state.speed = Number((event.target as HTMLSelectElement).value);
  });

  ($("fakultatif") as HTMLInputElement).addEventListener("change", (event) => {
    state.showFakultatif = (event.target as HTMLInputElement).checked;
    policy.showFakultatif = state.showFakultatif;
    requestFrame();
  });

  ($("search") as HTMLInputElement).addEventListener("change", (event) => {
    handleSearch((event.target as HTMLInputElement).value);
  });

  $("disclaimer").textContent = manifest.attribution.disclaimer;

  const about = $("about") as HTMLDialogElement;
  $("about-open").addEventListener("click", () => about.showModal());
  const hash = $("about-hash");
  hash.textContent = manifest.content_hash;
  hash.setAttribute("translate", "no");

  updateBanner();
  window.setInterval(updateBanner, 30_000);
}

/** The banner is time-dependent, so it must be re-evaluated, not set once. */
function updateBanner(): void {
  if (!manifest) return;
  const effective = new Date(`${manifest.effective_from}T00:00:00+07:00`);
  const banner = $("banner");
  const shouldShow = Date.now() < effective.getTime();
  if (shouldShow) {
    banner.textContent = manifest.attribution.preview_banner;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

async function main(): Promise<void> {
  await loadData();
  buildMap();
  // Built on first interaction, not at startup.
  const searchInput = $("search") as HTMLInputElement;
  searchInput.addEventListener("focus", buildSearchIndex, { once: true });
  searchInput.addEventListener("input", buildSearchIndex, { once: true });
  wireControls();
  // Only the LABEL is initialised here. Writing the inputs at startup can race a
  // user (or a test) that already moved the slider, silently resetting it.
  $("clock").textContent = hhmm(state.secondsOfDay);
  setMode(state.mode);
  // Let the first paint happen before the worker loads and parses the schedule:
  // LCP should not wait for ~1 MB of JSON.
  const start = () => {
    startWorker();
    tick();
  };
  if (document.readyState === "complete") {
    window.setTimeout(start, 0);
  } else {
    window.addEventListener("load", () => window.setTimeout(start, 0), { once: true });
  }
}

window.addEventListener("unhandledrejection", (event) => {
  showLoadError(
    `Gagal memuat aplikasi: ${String(event.reason ?? "kesalahan tidak diketahui")}`,
  );
});

void main().catch((error: unknown) => {
  showLoadError(`Gagal memuat data jadwal: ${String(error)}`);
});
