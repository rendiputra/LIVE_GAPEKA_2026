/**
 * Search across trains and stations, with grouped results.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { MapPin, Search, TrainFront, X } from "lucide-react";
import type { ScheduleSnapshot, Trip } from "../engine/types";
import { trainColour } from "../map/layers";

export interface TrainHit {
  readonly tripId: string;
  readonly trainNo: string;
  readonly name: string;
  readonly book: number;
  readonly relation: string;
}

export interface StationHit {
  readonly code: string;
  readonly name: string;
  readonly located: boolean;
  readonly disambiguator: string | null;
}

export interface SearchResults {
  readonly trains: readonly TrainHit[];
  readonly stations: readonly StationHit[];
}

export const MAX_TRAIN_HITS = 8;
export const MAX_STATION_HITS = 8;

function normalise(value: string): string {
  return value.trim().toLowerCase();
}

function trainHits(snapshot: ScheduleSnapshot, query: string): TrainHit[] {
  const needle = normalise(query);
  const hits: TrainHit[] = [];
  for (const trip of snapshot.trips) {
    const byNumber = trip.trainNo.toLowerCase().includes(needle);
    const byName = trip.name.toLowerCase().includes(needle);
    const byId = trip.tripId.toLowerCase().includes(needle);
    if (!byNumber && !byName && !byId) continue;
    hits.push({
      tripId: trip.tripId,
      trainNo: trip.trainNo,
      name: trip.name,
      book: trip.book,
      relation: trip.relation,
    });
    if (hits.length >= MAX_TRAIN_HITS) break;
  }
  return hits;
}

function stationHits(snapshot: ScheduleSnapshot, query: string): StationHit[] {
  const needle = normalise(query);
  const hits: StationHit[] = [];
  for (const station of snapshot.stations.values()) {
    const byCode = station.code.toLowerCase() === needle;
    const byName = station.officialName.toLowerCase().includes(needle);
    if (!byCode && !byName) continue;
    hits.push({
      code: station.code,
      name: station.officialName,
      located: station.lat !== null && station.lon !== null,
      disambiguator: station.disambiguator,
    });
    if (hits.length >= MAX_STATION_HITS) break;
  }
  return hits;
}

/** Pure search; the panel below renders its result. */
export function search(snapshot: ScheduleSnapshot, query: string): SearchResults {
  if (normalise(query).length === 0) return { trains: [], stations: [] };
  return {
    trains: trainHits(snapshot, query),
    stations: stationHits(snapshot, query),
  };
}

/** The empty-query shortlist (hubs first, so it is useful on first open). */
export function topSuggestions(
  snapshot: ScheduleSnapshot,
  limit = 6,
): Array<{ type: "train"; hit: TrainHit } | { type: "station"; hit: StationHit }> {
  const out: Array<{ type: "train"; hit: TrainHit } | { type: "station"; hit: StationHit }> = [];
  for (const trip of snapshot.trips) {
    if (out.length >= limit) break;
    out.push({
      type: "train",
      hit: {
        tripId: trip.tripId,
        trainNo: trip.trainNo,
        name: trip.name,
        book: trip.book,
        relation: trip.relation,
      },
    });
  }
  return out;
}

export function SearchPanel(props: {
  readonly snapshot: ScheduleSnapshot | null;
  readonly query: string;
  readonly onSelectTrain: (tripId: string) => void;
  readonly onSelectStation: (code: string, name: string) => void;
  readonly onClose: () => void;
  readonly open: boolean;
}): React.ReactElement | null {
  const [value, setValue] = useState(props.query);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setValue(props.query);
  }, [props.query]);

  useEffect(() => {
    if (props.open) inputRef.current?.focus();
  }, [props.open]);

  const results = useMemo(() => {
    if (!props.snapshot) return { trains: [], stations: [] };
    return search(props.snapshot, value);
  }, [props.snapshot, value]);

  if (!props.open) return null;

  const hasResults = results.trains.length > 0 || results.stations.length > 0;
  const isEmpty = normalise(value).length === 0;

  return (
    <div
      role="dialog"
      aria-label="Hasil pencarian"
      className="z-30 max-h-[60dvh] w-full overflow-hidden rounded-2xl border border-black/10 bg-white/98 shadow-lg backdrop-blur"
    >
      <div className="flex items-center gap-1.5 border-b border-black/5 px-3 py-2">
        <Search size={16} aria-hidden="true" className="shrink-0 text-neutral-400" />
        <label htmlFor="panel-search" className="sr-only">
          Cari KA, nama kereta atau stasiun
        </label>
        <input
          id="panel-search"
          ref={inputRef}
          type="search"
          autoComplete="off"
          spellCheck={false}
          placeholder="Cari KA 249, Gajayana, Gambir…"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="h-9 min-w-0 flex-1 bg-transparent text-sm text-neutral-900 placeholder:text-neutral-400 focus:outline-none"
        />
        <button
          type="button"
          aria-label="Tutup pencarian"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={props.onClose}
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>

      <div className="max-h-[calc(60dvh-3.5rem)] overflow-y-auto overscroll-contain">
        {isEmpty ? (
          <p className="px-4 py-6 text-center text-[13px] text-neutral-500">
            Ketik nomor KA, nama kereta atau nama stasiun. Coba{" "}
            <button
              type="button"
              className="font-semibold text-blue-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded"
              onClick={() => setValue("Gajayana")}
            >
              Gajayana
            </button>{" "}
            atau{" "}
            <button
              type="button"
              className="font-semibold text-blue-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded"
              onClick={() => setValue("Gambir")}
            >
              Gambir
            </button>
            .
          </p>
        ) : !hasResults ? (
          <p className="px-4 py-6 text-center text-[13px] text-neutral-500">
            Tidak ada hasil untuk “{value}”. Periksa ejaan atau coba nomor KA lain.
          </p>
        ) : (
          <div className="py-1">
            {results.trains.length > 0 ? (
              <section aria-label="Kereta Api">
                <h3 className="px-4 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
                  Kereta Api
                </h3>
                <ul>
                  {results.trains.map((hit) => (
                    <li key={`train-${hit.tripId}`}>
                      <button
                        type="button"
                        onClick={() => props.onSelectTrain(hit.tripId)}
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-blue-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-inset"
                      >
                        <span
                          aria-hidden="true"
                          className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{
                            backgroundColor: trainColour(hit.book, "reguler"),
                          }}
                        />
                        <TrainFront size={16} aria-hidden="true" className="shrink-0 text-neutral-400" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-semibold text-neutral-900">
                            KA {hit.trainNo}
                            {hit.name.trim() !== "" && hit.name.trim() !== hit.trainNo.trim()
                              ? ` · ${hit.name}`
                              : ""}
                          </span>
                          {hit.relation ? (
                            <span className="block truncate text-[12px] text-neutral-500 tabular-nums">
                              {hit.relation}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {results.stations.length > 0 ? (
              <section aria-label="Stasiun">
                <h3 className="px-4 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
                  Stasiun
                </h3>
                <ul>
                  {results.stations.map((hit) => (
                    <li key={`station-${hit.code}`}>
                      <button
                        type="button"
                        onClick={() => props.onSelectStation(hit.code, hit.name)}
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-blue-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-inset"
                      >
                        <MapPin size={16} aria-hidden="true" className="shrink-0 text-neutral-400" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-semibold text-neutral-900">
                            {hit.name}
                            <span className="ml-1.5 font-mono text-[12px] font-medium text-neutral-500">
                              {hit.code}
                            </span>
                          </span>
                          <span className="block text-[12px] text-neutral-500">
                            {hit.located
                              ? hit.disambiguator ?? "Stasiun"
                              : "Lokasi belum terpetakan — tampilkan jadwal"}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

export type { Trip };
