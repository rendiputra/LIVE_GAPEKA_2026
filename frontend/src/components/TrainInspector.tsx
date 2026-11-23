/**
 * The Train Inspector — the app's primary progressive-disclosure surface.
 *
 * State A (compact): header, telemetry, the next-stop hero banner and a
 * progress bar. State B (expanded): the full stop timeline, auto-scrolled so
 * the current leg sits near the top. Both `Stop`, `Pass` and `Untimed` rows are
 * shown; `Untimed` rows are distance markers, never pauses.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, ExternalLink, X } from "lucide-react";
import {
  arriveAbs,
  departAbs,
  type ScheduleSnapshot,
  type Trip,
} from "../engine/types";
import type { TrainPosition } from "../engine/types";
import { formatSod, formatSodHm } from "../engine/time";
import { trainColour } from "../map/layers";
import { nextStopAhead } from "../engine/queries";

export interface TrainInspectorProps {
  readonly trip: Trip;
  readonly position: TrainPosition | null;
  readonly elapsed: number;
  readonly snapshot: ScheduleSnapshot;
  readonly expanded: boolean;
  readonly following: boolean;
  readonly onToggleExpanded: () => void;
  readonly onClose: () => void;
  readonly onFollow: () => void;
  readonly onStationClick: (code: string, name: string) => void;
  readonly onOpenStationBoard: (code: string) => void;
  readonly onPanTo: (lat: number, lon: number, code: string) => void;
}

function stationName(snapshot: ScheduleSnapshot, code: string): string {
  const station = snapshot.stations.get(code);
  return station ? station.officialName : code;
}

function stationLine(
  snapshot: ScheduleSnapshot,
  code: string,
  fallback: string,
): { lat: number; lon: number } | null {
  const station = snapshot.stations.get(code);
  if (!station || station.lat === null || station.lon === null) return null;
  void fallback;
  return { lat: station.lat, lon: station.lon };
}

/** `23:35 WIB`, with seconds only when they are non-zero, and `+1 hari` when needed. */
export function formatStopTime(
  sod: number,
  dayOffset: number,
  includeSeconds = true,
): string {
  const base = includeSeconds && sod % 60 !== 0 ? formatSod(sod) : formatSodHm(sod);
  return `${base} WIB${dayOffset > 0 ? ` (+${dayOffset} hari)` : ""}`;
}

export function formatEta(minutes: number): string {
  if (minutes <= 0) return "sekarang";
  if (minutes < 60) return `±${minutes} mnt`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} jam` : `${hours} jam ${rest} mnt`;
}

export function formatSpeed(speedKmh: number): string {
  return `${Math.round(speedKmh)} km/jam`;
}

export function progressPercent(sM: number, totalLengthM: number): number {
  if (totalLengthM <= 0) return 0;
  return Math.min(100, Math.max(0, (sM / totalLengthM) * 100));
}

export function statusLabel(status: TrainPosition["status"]): string {
  return status === "running" ? "Running" : "At Station";
}

export function stopBadge(stopType: string): string {
  switch (stopType) {
    case "stop":
      return "Stop";
    case "pass":
      return "Pass";
    default:
      return "Untimed";
  }
}

/** The first row whose time is at or after `elapsed` — for the timeline marker. */
export function currentIndex(
  trip: Trip,
  elapsed: number,
): number {
  let best = -1;
  let bestTime = Number.POSITIVE_INFINITY;
  trip.rows.forEach((row, index) => {
    const depart = departAbs(row);
    if (depart === null) return;
    // A row below the current time: the current leg starts after it.
    if (depart >= elapsed && depart < bestTime) {
      bestTime = depart;
      best = index;
    }
  });
  // If every timed row is behind us, the train is at its terminus.
  if (best === -1) return trip.rows.length - 1;
  return best;
}

export function TrainInspector(props: TrainInspectorProps): React.ReactElement {
  const { trip, position, elapsed, snapshot, expanded, following } = props;
  const listRef = useRef<HTMLDivElement | null>(null);
  const currentRowRef = useRef<HTMLButtonElement | null>(null);
  const [userScrolled, setUserScrolled] = useState(false);

  // Reset the scroll guard whenever the card becomes compact again, so a
  // later re-expand auto-scrolls to the active leg instead of stranding the
  // list at the previous scroll offset.
  useEffect(() => {
    if (!expanded) {
      setUserScrolled(false);
    }
  }, [expanded]);

  const upcoming = useMemo(() => {
    // nextStopAhead works from a distance; the inspector knows the elapsed time.
    // Use the trip's distance from the position when available.
    const sM = position ? position.sM : 0;
    return nextStopAhead(trip, sM, elapsed);
  }, [elapsed, position, trip]);

  const currentRow = useMemo(() => currentIndex(trip, elapsed), [elapsed, trip]);

  useEffect(() => {
    if (!expanded || userScrolled) return;
    currentRowRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [expanded, userScrolled, currentRow]);

  const panToStation = useCallback(
    (code: string) => {
      const point = stationLine(snapshot, code, code);
      if (point) props.onPanTo(point.lat, point.lon, code);
    },
    [props, snapshot],
  );

  const colour = trainColour(trip.book, trip.serviceClass);
  const sM = position ? position.sM : 0;
  const speed = position ? position.speedKmh : 0;
  const inProgress = Boolean(position);

  return (
    <section
      aria-label={`Inspektori KA ${trip.trainNo}`}
      className="pointer-events-auto flex max-h-full w-full max-w-[380px] flex-col overflow-hidden rounded-3xl border border-black/10 bg-white/95 shadow-lg backdrop-blur"
    >
      {/* Header */}
      <header className="flex shrink-0 items-start gap-3 px-4 pt-4 pb-3">
        <span
          aria-hidden="true"
          className="mt-1 inline-block h-3 w-3 shrink-0 rounded-full border-2 border-white shadow"
          style={{ backgroundColor: colour }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[15px] font-bold text-neutral-900 tabular-nums">
              KA {trip.trainNo}
            </span>
            {trip.name.trim() !== "" && trip.name.trim() !== trip.trainNo.trim() ? (
              <span className="text-[15px] font-semibold text-neutral-800">
                {trip.name}
              </span>
            ) : null}
            {trip.hasUntimedMarkers ? (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                Estimasi kasar
              </span>
            ) : null}
          </div>
          <p
            className="mt-0.5 truncate text-[13px] text-neutral-500"
            title={relationLabel(trip, snapshot) || undefined}
          >
            {relationLabel(trip, snapshot)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className={`rounded-full px-2.5 py-1.5 text-[12px] font-semibold transition-[background-color,color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
              following
                ? "bg-blue-700 text-white hover:bg-blue-800"
                : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200"
            }`}
            aria-pressed={following}
            onClick={props.onFollow}
          >
            {following ? "Mengikuti" : "Ikuti KA"}
          </button>
          <button
            type="button"
            aria-label="Tutup inspektori"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            onClick={props.onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </header>

      {/* Telemetry */}
      <div className="flex shrink-0 items-center gap-3 border-y border-black/5 bg-neutral-50/70 px-4 py-2.5">
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold ${
            position?.status === "running"
              ? "bg-emerald-100 text-emerald-800"
              : "bg-blue-100 text-blue-800"
          }`}
        >
          <span
            aria-hidden="true"
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              position?.status === "running" ? "animate-pulse bg-emerald-600" : "bg-blue-600"
            }`}
          />
          {position ? statusLabel(position.status) : "Di luar jadwal"}
        </span>
        <span
          className="min-w-0 flex-1 truncate text-[13px] text-neutral-600"
          title={
            position
              ? `${stationName(snapshot, position.fromCode)} → ${stationName(snapshot, position.toCode)}`
              : undefined
          }
        >
          {position
            ? `${stationName(snapshot, position.fromCode)} → ${stationName(snapshot, position.toCode)}`
            : "Tidak aktif pada waktu ini"}
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[10px] font-semibold tracking-wide text-neutral-400 uppercase">
            Speed
          </span>
          <span className="block text-[15px] leading-tight font-bold text-neutral-900 tabular-nums">
            {inProgress ? formatSpeed(speed) : "—"}
          </span>
        </span>
      </div>

      {/* Next stop hero */}
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls="inspector-timeline"
        onClick={props.onToggleExpanded}
        className="group flex w-full shrink-0 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-blue-50/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-inset"
      >
        <span
          aria-hidden="true"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-700 text-white transition-[transform] duration-150 group-hover:scale-105"
        >
          <ChevronRight size={18} className={expanded ? "rotate-90" : ""} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] font-semibold tracking-wide text-blue-700 uppercase">
            {position?.status === "at_station" ? "At Station" : "Next Stop"}
          </span>
          <span className="mt-0.5 flex flex-wrap items-baseline gap-x-2 min-w-0">
            <span className="text-[16px] font-bold break-words text-neutral-900">
              {upcoming
                ? `${stationName(snapshot, upcoming.code)} (${upcoming.code})`
                : position?.nextStopCode
                  ? `${stationName(snapshot, position.nextStopCode)} (${position.nextStopCode})`
                  : "Tidak ada stop berikutnya"}
            </span>
          </span>
          <span className="mt-0.5 block text-[13px] text-neutral-600 tabular-nums">
            {upcoming
              ? `${formatStopTime(upcoming.sod, upcoming.dayOffset)} · ETA ${formatEta(upcoming.minutesAway)}`
              : position?.nextStopTime
                ? `${position.nextStopTime} WIB`
                : "Selesai"}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[11px] font-medium text-neutral-500">Perjalanan</span>
          <span className="block text-[13px] font-semibold text-neutral-900 tabular-nums">
            {Math.round(progressPercent(sM, trip.totalLengthM))}%
          </span>
        </span>
      </button>

      {/* Progress */}
      <div className="shrink-0 px-4 pb-2" role="progressbar" aria-valuenow={Math.round(progressPercent(sM, trip.totalLengthM))} aria-valuemin={0} aria-valuemax={100} aria-label="Kemajuan perjalanan">
        <div className="h-1.5 overflow-hidden rounded-full bg-neutral-100">
          <div
            className="h-full rounded-full bg-blue-700 transition-[width] duration-500"
            style={{ width: `${progressPercent(sM, trip.totalLengthM)}%` }}
          />
        </div>
        <span className="mt-1.5 block text-[12px] text-neutral-500">
          {expanded
            ? "Klik banner untuk menyembunyikan daftar stasiun"
            : `Semua stasiun (${trip.rows.length}) ▾`}
        </span>
      </div>

      {/* Timeline */}
      {expanded ? (
        <div
          id="inspector-timeline"
          ref={listRef}
          onScroll={() => setUserScrolled(true)}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-black/5"
        >
          <ol className="px-2 py-2">
            {trip.rows.map((row, index) => {
              const isCurrent = index === currentRow;
              const isPast = isPastRow(row.arriveSod, row.departSod, elapsed, row);
              const arrive = arriveAbs(row);
              const depart = departAbs(row);
              return (
                <li key={`${row.seq}-${row.stationCode}`}>
                  <button
                    type="button"
                    ref={isCurrent ? currentRowRef : undefined}
                    onClick={() => {
                      panToStation(row.stationCode);
                      props.onStationClick(row.stationCode, stationName(snapshot, row.stationCode));
                    }}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
                      isCurrent
                        ? "bg-blue-50 ring-1 ring-blue-600/30"
                        : "hover:bg-neutral-50"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2 ${
                        isCurrent
                          ? "border-blue-700 bg-blue-700"
                          : isPast
                            ? "border-neutral-300 bg-neutral-300"
                            : "border-neutral-400 bg-white"
                      }`}
                    />
                    <span
                      className={`min-w-0 flex-1 ${
                        isPast ? "text-neutral-400" : "text-neutral-800"
                      }`}
                    >
                      <span className="block truncate text-[13.5px] font-medium">
                        {stationName(snapshot, row.stationCode)} ({row.stationCode})
                      </span>
                      {isCurrent && position ? (
                        <span className="mt-0.5 inline-block rounded-full bg-blue-700 px-2 py-0.5 text-[10px] font-bold tracking-wide text-white uppercase">
                          Posisi saat ini
                        </span>
                      ) : null}
                      {isCurrent && !position ? (
                        <span className="mt-0.5 inline-block rounded-full bg-neutral-200 px-2 py-0.5 text-[10px] font-bold tracking-wide text-neutral-700 uppercase">
                          Stasiun asal
                        </span>
                      ) : null}
                    </span>
                    <span className="shrink-0 text-right">
                      <span
                        className={`block text-[12px] font-medium tabular-nums ${
                          isPast ? "text-neutral-400" : "text-neutral-700"
                        }`}
                      >
                        {row.arriveSod !== null
                          ? formatSodHm(row.arriveSod)
                          : row.departSod !== null
                            ? formatSodHm(row.departSod)
                            : "—"}
                      </span>
                      <span
                        className={`mt-0.5 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                          row.stopType === "stop"
                            ? "bg-blue-100 text-blue-800"
                            : row.stopType === "pass"
                              ? "bg-neutral-100 text-neutral-500"
                              : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {stopBadge(row.stopType)}
                      </span>
                    </span>
                    {arrive === null && depart === null ? (
                      <span className="sr-only">Tidak bertime</span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="border-t border-black/5 px-4 py-2.5">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-[13px] font-medium text-blue-700 transition-colors hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded-lg px-1 py-0.5"
              onClick={() => props.onOpenStationBoard(position?.fromCode ?? trip.rows[0]!.stationCode)}
            >
              <ExternalLink size={13} aria-hidden="true" />
              Lihat jadwal stasiun
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function isPastRow(
  _arrive: number | null,
  _depart: number | null,
  elapsed: number,
  row: Trip["rows"][number],
): boolean {
  const arrive = arriveAbs(row);
  if (arrive !== null && arrive < elapsed) return true;
  const depart = departAbs(row);
  return depart !== null && depart < elapsed;
}

function relationLabel(trip: Trip, snapshot: ScheduleSnapshot): string {
  if (trip.relation.trim() === "") return "";
  const [from, to] = trip.relation.split("-");
  if (!from || !to) return trip.relation;
  return `${stationName(snapshot, from)} (${from}) → ${stationName(snapshot, to)} (${to})`;
}

export { formatSod };
