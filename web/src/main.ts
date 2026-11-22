// Entry point (B4). Static site: no server, no API. All positions are computed
// in the worker from the exported schedule; the map only renders.

import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";

import { prepare, type Dataset, type TrainPosition } from "./engine/position";
import { defaultPolicy, type Manifest, type Policy, type TripData } from "./engine/types";

const DATA_BASE = `${import.meta.env.BASE_URL}data`;
const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

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

// --- time helpers -----------------------------------------------------------

const WIB_MS = 7 * 3600 * 1000;

function instantFor(dateIso: string, secondsOfDay: number): number {
  const [year, month, day] = dateIso.split("-").map(Number);
  return Date.UTC(year, month - 1, day, 0, 0, 0) - WIB_MS + secondsOfDay * 1000;
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

  dataset = prepare(
    manifest,
    stations.stations,
    segments.segments,
    trips.trips,
    trips.stop_types,
  );
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
}

// --- map --------------------------------------------------------------------

function buildMap(): void {
  map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: [OSM_TILES],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    center: [110.4, -7.2],
    zoom: 6.4,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

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
  $("status").textContent = `${positions.length} KA aktif · ${hhmm(state.secondsOfDay)} WIB` +
    (state.mode === "replay" ? ` · ${state.date}` : "");
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
        const isCurrent =
          Math.abs(trip.waypoints.s_m[i] - position.sM) < 1 ||
          code === position.fromCode ||
          code === position.toCode;
        return `<li class="${isCurrent ? "current" : ""}">
          <span>${stationName.get(code) ?? code}</span>
          <span class="t">${clock}</span>
          <span class="t">${stopTypes[trip.waypoints.stop_type[i]] ?? ""}</span>
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
}

function selectTrip(tripId: string): void {
  state.selectedTripId = tripId;
  state.selectedStation = null;
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

function buildSearchIndex(): void {
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
    .slice(0, 3000)
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
}

function wireControls(): void {
  $("mode-live").addEventListener("click", () => {
    state.mode = "live";
    $("mode-live").setAttribute("aria-checked", "true");
    $("mode-replay").setAttribute("aria-checked", "false");
    ($("replay-controls") as HTMLElement).hidden = true;
    requestFrame();
  });

  $("mode-replay").addEventListener("click", () => {
    state.mode = "replay";
    $("mode-live").setAttribute("aria-checked", "false");
    $("mode-replay").setAttribute("aria-checked", "true");
    ($("replay-controls") as HTMLElement).hidden = false;
    syncReplayInputs();
    requestFrame();
  });

  ($("date") as HTMLInputElement).addEventListener("change", (event) => {
    state.date = (event.target as HTMLInputElement).value || "2026-12-01";
    requestFrame();
  });

  ($("time") as HTMLInputElement).addEventListener("input", (event) => {
    state.secondsOfDay = Number((event.target as HTMLInputElement).value);
    $("clock").textContent = hhmm(state.secondsOfDay);
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

  const now = new Date();
  const effective = new Date(`${manifest.effective_from}T00:00:00+07:00`);
  if (now < effective) {
    const banner = $("banner");
    banner.textContent = manifest.attribution.preview_banner;
    banner.hidden = false;
  }
}

async function main(): Promise<void> {
  await loadData();
  buildMap();
  buildSearchIndex();
  wireControls();
  syncReplayInputs();
  startWorker();
  tick();
}

void main();
