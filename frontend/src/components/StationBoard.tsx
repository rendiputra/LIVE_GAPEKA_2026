/**
 * The station board: the next 10 departures in the coming 3 hours.
 */
import { useState } from "react";
import { X } from "lucide-react";
import type { BoardEntry } from "../engine/queries";
import { trainColour } from "../map/layers";

export function boardSortKey(entry: BoardEntry): number {
  return entry.departsAtMs;
}

export function formatBoardTime(entry: BoardEntry): string {
  return entry.dayOffset > 0
    ? `${entry.scheduledTime} (+${entry.dayOffset} hari)`
    : entry.scheduledTime;
}

export function isBoardable(entry: BoardEntry): boolean {
  return entry.serviceClass === "reguler";
}

export function nextBoardEntry(
  entries: readonly BoardEntry[],
  instant: number,
): BoardEntry | null {
  let best: BoardEntry | null = null;
  for (const entry of entries) {
    if (entry.departsAtMs < instant) continue;
    if (best === null || entry.departsAtMs < best.departsAtMs) best = entry;
  }
  return best;
}

export function StationBoard(props: {
  readonly code: string;
  readonly name: string;
  readonly located: boolean;
  readonly entries: readonly BoardEntry[];
  readonly loading: boolean;
  readonly onClose: () => void;
  readonly onSelectTrip: (tripId: string) => void;
  readonly onShowFakultatif: () => void;
}): React.ReactElement | null {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? props.entries : props.entries.filter(isBoardable);

  return (
    <section
      aria-label={`Jadwal ${props.name}`}
      className="pointer-events-auto flex max-h-[calc(100dvh-10rem)] w-full max-w-[380px] flex-col overflow-hidden rounded-3xl border border-black/10 bg-white/95 shadow-lg backdrop-blur"
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="truncate text-[16px] font-bold text-neutral-900">{props.name}</h2>
          <p className="mt-0.5 text-[12.5px] text-neutral-500 tabular-nums">
            {props.code} · 10 kereta berikutnya dalam 3 jam
            {!props.located ? " · lokasi belum terpetakan" : ""}
          </p>
        </div>
        <button
          type="button"
          aria-label="Tutup jadwal stasiun"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={props.onClose}
        >
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-16">
        {props.loading ? (
          <p className="px-3 py-8 text-center text-[13px] text-neutral-500">Memuat jadwal…</p>
        ) : visible.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <p className="text-[13px] text-neutral-500">
              Tidak ada keberangkatan dalam 3 jam ke depan.
            </p>
            {props.entries.some((entry) => !isBoardable(entry)) ? (
              <button
                type="button"
                className="mt-2 text-[13px] font-semibold text-blue-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded"
                onClick={props.onShowFakultatif}
              >
                Tampilkan KA fakultatif
              </button>
            ) : null}
          </div>
        ) : (
          <ol>
            {visible.map((entry) => (
              <li key={`${entry.tripId}-${entry.departsAtMs}`}>
                <button
                  type="button"
                  onClick={() => props.onSelectTrip(entry.tripId)}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-blue-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-inset"
                >
                  <span
                    aria-hidden="true"
                    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{
                      backgroundColor: trainColour(1, entry.serviceClass),
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold text-neutral-900">
                      KA {entry.trainNo}
                      {entry.name.trim() !== "" ? ` · ${entry.name}` : ""}
                    </span>
                    <span className="block truncate text-[12px] text-neutral-500 tabular-nums">
                      {entry.relation}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block text-[14px] font-bold text-neutral-900 tabular-nums">
                      {formatBoardTime(entry)}
                    </span>
                    {entry.coarse ? (
                      <span className="mt-0.5 inline-block rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                        Estimasi kasar
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}

        {props.entries.some((entry) => !isBoardable(entry)) &&
        !showAll &&
        !props.loading &&
        visible.length > 0 ? (
          <button
            type="button"
            className="mx-auto mt-2 block text-[12.5px] font-medium text-neutral-500 underline-offset-2 hover:text-neutral-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded px-2 py-1"
            onClick={() => setShowAll(true)}
          >
            Tampilkan juga KA fakultatif ({props.entries.filter((entry) => !isBoardable(entry)).length})
          </button>
        ) : null}
      </div>
    </section>
  );
}
