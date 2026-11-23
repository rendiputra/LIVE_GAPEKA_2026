/**
 * The app shell.
 *
 * The map is the star: it fills the viewport and everything else floats above
 * it. There is deliberately no top banner and no footer disclaimer bar — the
 * estimate status lives in the top-right pill and the full text in "Tentang"
 * (ADR 002 amendment, 2026-11-23).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSnapshot } from "./worker/fetchSchedule";
import { createWorkerClient, type WorkerClient } from "./worker/client";
import type { WorkerResponse } from "./worker/host";
import { stationBoard } from "./engine/queries";
import { wibFromEpochMs } from "./engine/time";
import type { Policy, ScheduleSnapshot, TrainPosition } from "./engine/types";
import { LiveMap, type MapStatus } from "./map/LiveMap";
import { BASEMAPS, OVERLAYS, type BasemapId, type OverlayId } from "./map/sources";
import {
  advance,
  backToLive,
  liveInstant,
  nudge,
  scrubTo,
  withPlaying,
  withSpeed,
  type ClockState,
  type ReplaySpeed,
} from "./map/clock";
import { statusPillLabel } from "./engine/schedule";
import {
  AboutButton,
  FilterButton,
  FilterPopover,
  LayersButton,
  LayersPopover,
  SearchPill,
  StatusPill,
} from "./components/controls";
import { AboutModal } from "./components/AboutModal";
import { SearchPanel } from "./components/SearchPanel";
import { StationBoard } from "./components/StationBoard";
import { TrainInspector } from "./components/TrainInspector";
import { TimeTravelDock, dateLabel } from "./components/TimeTravelDock";
import { OverlayLegend, isOverlayActive } from "./components/OverlayLegend";
import type { BoardEntry } from "./engine/queries";
import type {
  PositionsFeature,
  PositionsFeatureCollection,
} from "./worker/geojson";

type WorkerState = "loading" | "ready" | "error";

interface SelectedStation {
  readonly code: string;
  readonly name: string;
}

interface PanRequest {
  readonly lat: number;
  readonly lon: number;
  readonly code: string;
  readonly at: number;
}

interface AppState {
  readonly snapshot: ScheduleSnapshot | null;
  readonly workerState: WorkerState;
  readonly workerError: string | null;
  readonly clock: ClockState;
  readonly selectedTripId: string | null;
  readonly selectedStation: SelectedStation | null;
  readonly board: readonly BoardEntry[] | null;
  readonly boardLoading: boolean;
  readonly showFakultatif: boolean;
  readonly basemap: BasemapId;
  readonly overlay: OverlayId;
  readonly layersOpen: boolean;
  readonly filterOpen: boolean;
  readonly aboutOpen: boolean;
  readonly timelineExpanded: boolean;
  readonly following: boolean;
  readonly searchOpen: boolean;
  readonly searchQuery: string;
  readonly tilesError: string | null;
  readonly trainCount: number;
  readonly telemetry: TrainPosition | null;
  readonly trains: PositionsFeatureCollection | null;
  readonly panRequest: PanRequest | null;
}

const INITIAL: AppState = {
  snapshot: null,
  workerState: "loading",
  workerError: null,
  clock: liveInstant(Date.now()),
  selectedTripId: null,
  selectedStation: null,
  board: null,
  boardLoading: false,
  showFakultatif: false,
  basemap: BASEMAPS.default,
  overlay: OVERLAYS.default,
  layersOpen: false,
  filterOpen: false,
  aboutOpen: false,
  timelineExpanded: false,
  following: false,
  searchOpen: false,
  searchQuery: "",
  tilesError: null,
  trainCount: 0,
  telemetry: null,
  trains: null,
  panRequest: null,
};

function policyFor(snapshot: ScheduleSnapshot | null, showFakultatif: boolean): Policy {
  const base = snapshot?.policy;
  return {
    calendar_policy: base?.calendar_policy ?? "regular_daily_assumed",
    show_fakultatif: showFakultatif,
    enforce_effective_from: false,
    geometry_policy: base?.geometry_policy ?? "complete_and_estimated",
    accel_time_s: base?.accel_time_s ?? 60,
    origin_lead_s: base?.origin_lead_s ?? 0,
    terminal_linger_s: base?.terminal_linger_s ?? 0,
    max_day_offset: base?.max_day_offset ?? 2,
  };
}

function featureToPosition(feature: PositionsFeature): TrainPosition {
  const p = feature.properties;
  return {
    tripId: p.tripId,
    trainNo: p.trainNo,
    name: p.name,
    relation: p.relation,
    book: p.book,
    lat: feature.geometry.coordinates[1],
    lon: feature.geometry.coordinates[0],
    bearing: p.bearing,
    status: p.status as TrainPosition["status"],
    sM: p.sM,
    fromCode: p.fromCode,
    toCode: p.toCode,
    nextStopCode: p.nextStopCode,
    nextStopTime: p.nextStopTime,
    speedKmh: p.speedKmh,
    estimated: true,
    coarse: p.coarse,
    hasBypassedWaypoints: p.hasBypassedWaypoints,
    hasStraightLineSegment: p.hasStraightLineSegment,
    serviceClass: p.serviceClass as TrainPosition["serviceClass"],
    motionModel: p.motionModel as TrainPosition["motionModel"],
  };
}

export function App(): React.ReactElement {
  const [state, setState] = useState<AppState>(INITIAL);
  const snapshotRef = useRef<ScheduleSnapshot | null>(null);
  const clientRef = useRef<WorkerClient | null>(null);
  const instantRef = useRef(Date.now());
  const clockRef = useRef<ClockState>(state.clock);
  const telemetryThrottle = useRef(0);
  const layersTriggerRef = useRef<HTMLButtonElement | null>(null);
  const filterTriggerRef = useRef<HTMLButtonElement | null>(null);
  const selectedTripIdRef = useRef<string | null>(state.selectedTripId);
  selectedTripIdRef.current = state.selectedTripId;

  const set = useCallback((patch: Partial<AppState>) => {
    setState((previous) => {
      if (patch.clock) clockRef.current = patch.clock;
      return { ...previous, ...patch };
    });
  }, []);

  const mapRef = useRef<import("maplibre-gl").Map | null>(null);

  // --- worker ---
  useEffect(() => {
    let cancelled = false;
    const worker = new Worker(new URL("./worker/positions.worker.ts", import.meta.url), {
      type: "module",
    });

    const handlers = {
      onReady: () => {
        if (!cancelled) set({ workerState: "ready", workerError: null });
      },
      onPositions: (response: Extract<WorkerResponse, { type: "positions" }>) => {
        if (cancelled) return;
        set({ trains: response.geojson, trainCount: response.count });
        const nowMs = Date.now();
        if (nowMs - telemetryThrottle.current >= 1_000) {
          telemetryThrottle.current = nowMs;
          const selected = selectedTripIdRef.current;
          if (selected) {
            const feature = response.geojson.features.find(
              (entry) => entry.id === selected,
            );
            set({ telemetry: feature ? featureToPosition(feature) : null });
          }
        }
      },
      onBoard: (response: Extract<WorkerResponse, { type: "board" }>) => {
        if (!cancelled) set({ board: response.entries, boardLoading: false });
      },
      onError: (response: Extract<WorkerResponse, { type: "error" }>) => {
        if (!cancelled) set({ workerState: "error", workerError: response.message });
      },
    };

    const { client } = createWorkerClient(worker, handlers);
    clientRef.current = client;
    client.init();

    // The same payload is needed on the main thread for search and the
    // inspector. Parsing 1.1 MB here is a one-off.
    void fetchSnapshot(`${import.meta.env.BASE_URL.replace(/\/+$/, "")}/data`)
      .then((snapshot) => {
        if (cancelled) return;
        snapshotRef.current = snapshot;
        set({ snapshot });
      })
      .catch((error: unknown) => {
        if (!cancelled) set({ workerState: "error", workerError: String(error) });
      });

    return () => {
      cancelled = true;
      worker.terminate();
      clientRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- live loop: ask the worker, never compute positions locally ---
  //
  // IMPORTANT: `requestAnimationFrame` hands us a DOMHighResTimeStamp measured
  // since page load, NOT an epoch millisecond. The instant sent to the worker
  // must be epoch time, so the loop always derives it from `Date.now()` and
  // uses the rAF timestamp only as a frame counter. Feeding the rAF timestamp
  // into `wibFromEpochMs` produced 1970-01-01.
  useEffect(() => {
    let cancelled = false;
    let lastTick = Date.now();

    const tick = (): void => {
      if (cancelled) return;
      const clock = clockRef.current;
      const nowMs = Date.now();
      const elapsed = nowMs - lastTick;
      lastTick = nowMs;

      let instant = nowMs;
      if (clock.mode === "sim") {
        const advanced = clock.playing ? advance(clock, elapsed, nowMs) : clock;
        instant = advanced.instant;
        if (advanced.instant !== clock.instant) {
          clockRef.current = advanced;
          setState((previous) => ({ ...previous, clock: advanced }));
        }
      } else {
        // Live: the instant IS the wall clock; nothing to store.
        clockRef.current = { ...clock, instant: nowMs };
      }
      instantRef.current = instant;
      clientRef.current?.requestPositions(
        instant,
        policyFor(snapshotRef.current, stateRef.current.showFakultatif),
      );
      requestAnimationFrame(tick);
    };

    const raf = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.showFakultatif]);

  const stateRef = useRef(state);
  stateRef.current = state;

  // Escape dismisses the top active layer, in order:
  // search dropdown > layers popover > about modal > inspector/board.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      const current = stateRef.current;
      if (current.searchOpen) {
        set({ searchOpen: false });
        return;
      }
      if (current.filterOpen) {
        set({ filterOpen: false });
        return;
      }
      if (current.layersOpen) {
        set({ layersOpen: false });
        return;
      }
      if (current.aboutOpen) {
        set({ aboutOpen: false });
        return;
      }
      if (current.selectedTripId || current.selectedStation) {
        set({
          selectedTripId: null,
          selectedStation: null,
          board: null,
          telemetry: null,
        });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [set]);

  const selectedTrip = useMemo(() => {
    if (!state.snapshot || !state.selectedTripId) return null;
    return state.snapshot.trips.find((trip) => trip.tripId === state.selectedTripId) ?? null;
  }, [state.snapshot, state.selectedTripId]);

  const selectedPosition = useMemo(() => {
    if (!state.snapshot || !state.selectedTripId) return null;
    return state.telemetry?.tripId === state.selectedTripId ? state.telemetry : null;
  }, [state.snapshot, state.selectedTripId, state.telemetry]);

  const elapsed = useMemo(
    () => wibFromEpochMs(state.clock.instant).secondsOfDay,
    [state.clock.instant],
  );

  const pillLabel = useMemo(() => {
    const base = statusPillLabel(wibFromEpochMs(state.clock.instant).secondsOfDay);
    return state.clock.mode === "live" ? base : base.replace("Live", "Simulasi");
  }, [state.clock.instant, state.clock.mode]);

  const onSelectTrain = useCallback(
    (tripId: string) => {
      set({
        selectedTripId: tripId,
        selectedStation: null,
        board: null,
        timelineExpanded: false,
        searchOpen: false,
        searchQuery: "",
      });
    },
    [set],
  );

  const onSelectStation = useCallback(
    (code: string, name: string) => {
      set({
        selectedStation: { code, name },
        selectedTripId: null,
        board: [],
        boardLoading: true,
        searchOpen: false,
        searchQuery: "",
      });
    },
    [set],
  );

  // Load the board whenever a station is selected.
  useEffect(() => {
    const station = state.selectedStation;
    if (!station || !state.snapshot) return;
    const entries = stationBoard(
      state.snapshot,
      station.code,
      instantRef.current,
      policyFor(state.snapshot, state.showFakultatif),
    );
    set({ board: entries, boardLoading: false });
  }, [state.selectedStation, state.snapshot, state.showFakultatif, set]);

  const onTrainClick = useCallback(
    (tripId: string) => onSelectTrain(tripId),
    [onSelectTrain],
  );

  const onStationClick = useCallback(
    (code: string) => {
      const name = state.snapshot?.stations.get(code)?.officialName ?? code;
      onSelectStation(code, name);
    },
    [onSelectStation, state.snapshot],
  );

  const onTilesError = useCallback(
    (message: string) => {
      if (message) set({ tilesError: message });
    },
    [set],
  );

  const onStatus = useCallback(
    (status: MapStatus) => {
      if (status.status === "error" && status.error) {
        set({ workerState: "error", workerError: status.error });
      } else if (status.status === "ready") {
        set({ workerState: "ready" });
      }
    },
    [set],
  );

  const scrub = useCallback(
    (minutesOfDay: number) => {
      const clock = scrubTo(
        clockRef.current,
        Math.floor(minutesOfDay / 60),
        minutesOfDay % 60,
      );
      clockRef.current = clock;
      set({ clock });
    },
    [set],
  );

  const nudgeBy = useCallback(
    (minutes: number) => {
      const clock = nudge(clockRef.current, minutes);
      clockRef.current = clock;
      set({ clock });
    },
    [set],
  );

  const togglePlay = useCallback(() => {
    const clock = withPlaying(clockRef.current, !clockRef.current.playing);
    clockRef.current = clock;
    set({ clock });
  }, [set]);

  const changeSpeed = useCallback(
    (speed: ReplaySpeed) => {
      const current = clockRef.current;
      const clock = withSpeed(
        current.mode === "live" ? { ...current, mode: "sim" as const, playing: true } : current,
        speed,
      );
      clockRef.current = clock;
      set({ clock });
    },
    [set],
  );

  const backToLiveNow = useCallback(() => {
    const clock = backToLive(clockRef.current, Date.now());
    clockRef.current = clock;
    set({ clock });
  }, [set]);

  const setDate = useCallback(
    (iso: string) => {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
      if (!match) return;
      const sod = wibFromEpochMs(clockRef.current.instant).secondsOfDay;
      const instant =
        Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) -
        7 * 3600 * 1000 +
        sod * 1000;
      const clock: ClockState = {
        ...clockRef.current,
        mode: "sim",
        instant,
        playing: false,
      };
      clockRef.current = clock;
      set({ clock });
    },
    [set],
  );

  const onPanTo = useCallback(
    (lat: number, lon: number, code: string) => {
      set({ panRequest: { lat, lon, code, at: Date.now() } });
    },
    [set],
  );

  // Pan the map to a station clicked in the inspector timeline.
  useEffect(() => {
    const request = state.panRequest;
    if (!request) return;
    mapRef.current?.easeTo({
      center: [request.lon, request.lat],
      zoom: 12,
      duration: 600,
      essential: true,
    });
  }, [state.panRequest]);

  return (
    <div className="relative h-[100dvh] w-[100vw] overflow-hidden bg-neutral-100">
      {/* Z-index scale:
          modal (Tentang)  z-50 > search + layers popover  z-40 >
          status pill  z-30 > inspector / board / dock / legend  z-20.
          No parent creates a stacking context that traps the dropdown. */}
      <div className="absolute inset-0 -z-0">
        <LiveMap
          snapshot={state.snapshot}
          selectedTripId={state.selectedTripId}
          basemap={state.basemap}
          overlay={state.overlay}
          trains={state.trains}
          follow={state.following}
          onTrainClick={onTrainClick}
          onStationClick={onStationClick}
          onTilesError={onTilesError}
          onStatus={onStatus}
          onDrag={() => {
            if (stateRef.current.following) set({ following: false });
          }}
          onInstance={(map) => {
            mapRef.current = map;
          }}
        />
      </div>

      {/* Top controls. One pointer-events-none wrapper; only real controls
          re-enable events, so the bar never swallows map clicks.
          Row 1: [search (flex-1 min-w-0)] [filter] [tentang]
          Row 2 (mobile): [status pill] ......... [layers]
          Desktop: row 1 left keeps search/filter/tentang, right keeps
          status pill + layers on the same line, generously spaced. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-40 flex flex-col gap-2 p-3 sm:p-4">
        <div className="flex items-start gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <div className="pointer-events-auto min-w-0 flex-1 sm:max-w-sm">
              <SearchPill
                query={state.searchQuery}
                onChange={(value) =>
                  set({ searchQuery: value, searchOpen: value.trim().length > 0 })
                }
                onClear={() => set({ searchQuery: "", searchOpen: false })}
              />
            </div>
            <div className="pointer-events-auto relative flex shrink-0 items-center gap-2">
              <FilterButton
                buttonRef={filterTriggerRef}
                active={state.showFakultatif}
                open={state.filterOpen}
                onToggle={() => set({ filterOpen: !state.filterOpen })}
              />
              <FilterPopover
                open={state.filterOpen}
                showFakultatif={state.showFakultatif}
                onSet={(value) => set({ showFakultatif: value })}
                onClose={() => set({ filterOpen: false })}
                triggerRef={filterTriggerRef}
              />
              <AboutButton onOpen={() => set({ aboutOpen: true })} />
            </div>
          </div>

          {/* Desktop cluster (>= lg). */}
          <div className="hidden shrink-0 items-start gap-2 lg:flex">
            <div className="pointer-events-auto">
              <StatusPill
                mode={state.clock.mode}
                label={pillLabel}
                dateLabel={dateLabel(state.clock.instant)}
                activeCount={state.trainCount}
                snapshotReady={state.workerState === "ready" || state.snapshot !== null}
                error={state.tilesError ?? state.workerError}
              />
            </div>
            <div className="pointer-events-auto relative">
              <LayersButton
                buttonRef={layersTriggerRef}
                onToggle={() => set({ layersOpen: !state.layersOpen })}
              />
              <LayersPopover
                open={state.layersOpen}
                basemap={state.basemap}
                overlay={state.overlay}
                onBasemap={(basemap) => set({ basemap, layersOpen: false })}
                onOverlay={(overlay) => set({ overlay, layersOpen: false })}
                onClose={() => set({ layersOpen: false })}
                triggerRef={layersTriggerRef}
              />
            </div>
          </div>
        </div>

        {/* Mobile/tablet row 2: status pill left, layers right. Never
            overlaps row 1 because it is a sibling in the same flow. */}
        <div className="flex items-center justify-between gap-2 lg:hidden">
          <div className="pointer-events-auto min-w-0">
            <StatusPill
              mode={state.clock.mode}
              label={pillLabel}
              dateLabel={dateLabel(state.clock.instant)}
              activeCount={state.trainCount}
              snapshotReady={state.workerState === "ready" || state.snapshot !== null}
              error={state.tilesError ?? state.workerError}
            />
          </div>
          <div className="pointer-events-auto relative shrink-0">
            <LayersButton
              onToggle={() => set({ layersOpen: !state.layersOpen })}
            />
            <LayersPopover
              open={state.layersOpen}
              basemap={state.basemap}
              overlay={state.overlay}
              onBasemap={(basemap) => set({ basemap, layersOpen: false })}
              onOverlay={(overlay) => set({ overlay, layersOpen: false })}
              onClose={() => set({ layersOpen: false })}
            />
          </div>
        </div>

        {/* Search results float above everything except the About modal. */}
        {state.searchOpen ? (
          <div className="pointer-events-none mt-1 max-w-sm">
            <SearchPanel
              snapshot={state.snapshot}
              query={state.searchQuery}
              open
              onSelectTrain={onSelectTrain}
              onSelectStation={onSelectStation}
              onClose={() => set({ searchOpen: false })}
            />
          </div>
        ) : null}
      </div>

      {/* Inspector. Fixed below the top stack on desktop (never moves when
          Search opens — the dropdown floats over it at z-40 > z-20) and above
          the dock on mobile, capped so its header and hero can never slide
          under the top controls. */}
      {selectedTrip ? (
        <div className="absolute inset-x-3 top-[136px] bottom-24 z-20 flex justify-center sm:inset-x-auto sm:top-[76px] sm:bottom-[150px] sm:left-3 sm:justify-start">
          <TrainInspector
            trip={selectedTrip}
            position={selectedPosition}
            elapsed={elapsed}
            snapshot={state.snapshot!}
            expanded={state.timelineExpanded}
            following={state.following}
            onToggleExpanded={() => set({ timelineExpanded: !state.timelineExpanded })}
            onClose={() => set({ selectedTripId: null, telemetry: null })}
            onFollow={() => set({ following: !state.following })}
            onStationClick={(code, name) => onSelectStation(code, name)}
            onOpenStationBoard={(code) =>
              onSelectStation(code, state.snapshot?.stations.get(code)?.officialName ?? code)
            }
            onPanTo={onPanTo}
          />
        </div>
      ) : null}

      {state.selectedStation ? (
        <div className="absolute inset-x-3 top-[136px] bottom-24 z-20 flex justify-center sm:inset-x-auto sm:top-[76px] sm:bottom-[150px] sm:left-3 sm:justify-start">
          <StationBoard
            code={state.selectedStation.code}
            name={state.selectedStation.name}
            located={
              state.snapshot?.stations.get(state.selectedStation.code)?.lat !== null &&
              state.snapshot?.stations.get(state.selectedStation.code)?.lat !== undefined
            }
            entries={state.board ?? []}
            loading={state.boardLoading}
            onClose={() => set({ selectedStation: null, board: null })}
            onSelectTrip={onSelectTrain}
            onShowFakultatif={() => set({ showFakultatif: true })}
          />
        </div>
      ) : null}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center pb-3 sm:pb-4">
        <TimeTravelDock
          mode={state.clock.mode}
          instant={state.clock.instant}
          playing={state.clock.playing}
          speed={state.clock.speed}
          onScrub={scrub}
          onNudge={nudgeBy}
          onTogglePlay={togglePlay}
          onSpeed={changeSpeed}
          onBackToLive={backToLiveNow}
          onDate={setDate}
        />
      </div>

      {/* Bug 2: ORM mini-legend, only while an overlay is active.
          Bottom-right, above the dock. On desktop the inspector lives on the
          left, so both fit. On a phone the inspector/board spans nearly the
          full width, so the legend steps aside while a panel is open instead
          of covering the stop list; it returns when the panel closes. */}
      {isOverlayActive(state.overlay) ? (
        <div
          data-testid="overlay-legend"
          className={`pointer-events-none absolute right-3 bottom-24 z-20 justify-end sm:right-3 sm:bottom-20 ${
            selectedTrip || state.selectedStation ? "hidden lg:flex" : "flex"
          }`}
        >
          <OverlayLegend overlay={state.overlay} onClose={() => {}} />
        </div>
      ) : null}

      {state.workerState === "loading" && state.snapshot === null ? (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center bg-neutral-50/70 backdrop-blur-sm"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-3 rounded-2xl bg-white px-5 py-4 shadow-lg">
            <span
              aria-hidden="true"
              className="h-4 w-4 animate-spin rounded-full border-2 border-neutral-200 border-t-blue-700"
            />
            <p className="text-[14px] font-medium text-neutral-700">
              Memuat jadwal Gapeka 2026…
            </p>
          </div>
        </div>
      ) : null}

      {state.workerState === "error" && state.snapshot === null ? (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center bg-neutral-50/80 p-6"
          role="alert"
        >
          <div className="max-w-sm rounded-3xl bg-white p-6 text-center shadow-lg">
            <h2 className="text-[16px] font-bold text-neutral-900">
              Jadwal tidak dapat dimuat
            </h2>
            <p className="mt-2 text-[13.5px] leading-relaxed text-neutral-600">
              {state.workerError ?? "Periksa koneksi internet Anda lalu muat ulang halaman."}
            </p>
            <button
              type="button"
              className="mt-4 inline-flex h-10 items-center rounded-full bg-blue-700 px-5 text-sm font-semibold text-white transition-colors hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
              onClick={() => window.location.reload()}
            >
              Muat ulang
            </button>
          </div>
        </div>
      ) : null}

      <AboutModal
        open={state.aboutOpen}
        versionName={state.snapshot?.versionName ?? null}
        effectiveFrom={state.snapshot?.effectiveFrom ?? null}
        effectiveTo={state.snapshot?.effectiveTo ?? null}
        contentHash={state.snapshot?.contentHash ?? null}
        trips={state.snapshot?.trips.length ?? 0}
        segments={
          state.snapshot
            ? new Set(
                state.snapshot.trips.flatMap((trip) =>
                  trip.segments.map((segment) => `${segment.fromCode}|${segment.toCode}`),
                ),
              ).size
            : 0
        }
        stations={state.snapshot?.stations.size ?? 0}
        attribution={state.snapshot?.attribution ?? null}
        onClose={() => set({ aboutOpen: false })}
      />
    </div>
  );
}
