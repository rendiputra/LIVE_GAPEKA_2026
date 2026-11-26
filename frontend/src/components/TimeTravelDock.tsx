/**
 * The realtime time-travel dock.
 *
 * Live by default. Every control switches to Simulasi; only `Kembali ke Live`
 * goes back. Scrubbing updates the trains while dragging (the engine is called
 * per input event, and the worker coalesces it).
 */
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { wibFromEpochMs } from "../engine/time";
import { REPLAY_SPEEDS, type ReplaySpeed } from "../map/clock";
import { PlayPauseButton } from "./controls";

const MONTHS = [
  "",
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "Mei",
  "Jun",
  "Jul",
  "Agu",
  "Sep",
  "Okt",
  "Nov",
  "Des",
];

export function formatDockTime(instant: number): string {
  const { secondsOfDay } = wibFromEpochMs(instant);
  const hours = String(Math.floor(secondsOfDay / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((secondsOfDay % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes} WIB`;
}

export function dateLabel(instant: number): string {
  const { date } = wibFromEpochMs(instant);
  return `${date.day} ${MONTHS[date.month] ?? ""} ${date.year}`;
}

export function simLabel(instant: number): string {
  return `Simulasi (Estimasi) · ${formatDockTime(instant)}`;
}

export function scrubMinutes(sliderValue: number): number {
  return ((sliderValue % (24 * 60)) + 24 * 60) % (24 * 60);
}

export function nudgeMinutes(minutes: number): number {
  return minutes;
}

export interface TimeTravelDockProps {
  readonly mode: "live" | "sim";
  readonly instant: number;
  readonly playing: boolean;
  readonly speed: ReplaySpeed;
  readonly onScrub: (minutesOfDay: number) => void;
  readonly onNudge: (minutes: number) => void;
  readonly onTogglePlay: () => void;
  readonly onSpeed: (speed: ReplaySpeed) => void;
  readonly onBackToLive: () => void;
  readonly onDate: (iso: string) => void;
}

export function TimeTravelDock(props: TimeTravelDockProps): React.ReactElement {
  const { date } = wibFromEpochMs(props.instant);
  const minutesOfDay = Math.floor(wibFromEpochMs(props.instant).secondsOfDay / 60);
  const [dragging, setDragging] = useState(false);
  const sliderRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!dragging && sliderRef.current) {
      // Re-sync the control when the clock moves on its own (Live mode, play).
      sliderRef.current.value = String(minutesOfDay);
    }
  }, [dragging, minutesOfDay]);

  const live = props.mode === "live";

  return (
    <div
      aria-label="Kontrol waktu"
      className="pointer-events-auto flex max-w-[calc(100vw-1.5rem)] items-center gap-1.5 rounded-full border border-black/10 bg-white/95 px-3 py-2 shadow-lg backdrop-blur sm:gap-2"
    >
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${live ? "animate-pulse bg-emerald-500" : "bg-amber-500"}`}
      />

      {/* Hidden below `sm`: the 24 h scrubber next to them does the same job,
          and two 48px buttons are what pushed the Simulasi dock off-screen on
          a 390px phone (429px wide against 366px available). */}
      <div className="hidden shrink-0 items-center gap-1 sm:flex">
        <button
          type="button"
          title="−15 menit"
          className="inline-flex h-8 items-center rounded-full px-2 text-[12px] font-semibold text-neutral-700 tabular-nums transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={() => props.onNudge(nudgeMinutes(-15))}
        >
          −15m
          {/* The accessible name must contain the visible text (WCAG 2.5.3), so
              it is extended here instead of replaced with an aria-label. */}
          <span className="sr-only">, mundurkan 15 menit</span>
        </button>
        <button
          type="button"
          title="+15 menit"
          className="inline-flex h-8 items-center rounded-full px-2 text-[12px] font-semibold text-neutral-700 tabular-nums transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={() => props.onNudge(nudgeMinutes(15))}
        >
          +15m
          <span className="sr-only">, majukan 15 menit</span>
        </button>
      </div>

      <input
        ref={sliderRef}
        type="range"
        aria-label="Geser waktu dalam 24 jam"
        min={0}
        max={1439}
        step={1}
        defaultValue={minutesOfDay}
        onPointerDown={() => setDragging(true)}
        onPointerUp={() => setDragging(false)}
        onInput={(event) => {
          const value = Number((event.target as HTMLInputElement).value);
          props.onScrub(scrubMinutes(value));
        }}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 sm:w-48 sm:flex-none"
      />

      <span className="hidden shrink-0 text-[13px] font-bold text-neutral-900 tabular-nums md:inline">
        {formatDockTime(props.instant)}
      </span>

      <label className="hidden shrink-0 items-center gap-1.5 lg:flex">
        <span className="sr-only">Tanggal</span>
        <input
          type="date"
          aria-label="Tanggal simulasi"
          value={`${String(date.year).padStart(4, "0")}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`}
          onChange={(event) => {
            if (event.target.value) props.onDate(event.target.value);
          }}
          className="h-8 rounded-lg border border-black/10 bg-white px-1.5 text-[12px] text-neutral-800 tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        />
      </label>

      <PlayPauseButton playing={props.playing} onToggle={props.onTogglePlay} />

      <div className="hidden shrink-0 items-center gap-0.5 sm:flex" role="group" aria-label="Kecepatan putar">
        {REPLAY_SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            aria-pressed={props.speed === speed}
            className={`rounded-full px-2 py-1 text-[11px] font-semibold tabular-nums transition-[background-color,color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
              props.speed === speed
                ? "bg-blue-700 text-white"
                : "text-neutral-600 hover:bg-neutral-100"
            }`}
            onClick={() => props.onSpeed(speed)}
          >
            {speed}x
          </button>
        ))}
      </div>

      {live ? null : (
        <button
          type="button"
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-blue-700 px-3 text-[12.5px] font-semibold text-white transition-colors hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
          onClick={props.onBackToLive}
        >
          <RotateCcw size={14} aria-hidden="true" />
          Kembali ke Live
        </button>
      )}

      <span className="sr-only" aria-live="polite">
        {live ? `Live, ${formatDockTime(props.instant)}` : `Simulasi, ${formatDockTime(props.instant)}`}
      </span>
    </div>
  );
}

export { ChevronLeft, ChevronRight };
