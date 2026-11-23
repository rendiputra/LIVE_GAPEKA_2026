/**
 * The OpenRailwayMap mini-legend.
 *
 * Shown ONLY while an ORM overlay is active. Every row is community data
 * (OpenStreetMap tags as rendered by OpenRailwayMap), never Gapeka data, and
 * the summary says so explicitly — including that `maxspeed` from the overlay
 * is the technical line speed, which is a different thing from the printed
 * maximum speed in the Gapeka timetable.
 */
import { useState } from "react";
import { ChevronDown, TrainTrack } from "lucide-react";
import { OVERLAYS, type OverlayId } from "../map/sources";

export interface LegendRow {
  readonly id: string;
  readonly label: string;
  readonly source: "openrailwaymap" | "gapeka";
  readonly swatch: "track" | "siding" | "yard" | "switch" | "crossover" | "maxspeed" | "speed-signal" | "bridge";
}

export const LEGEND_ROWS: readonly LegendRow[] = [
  { id: "main-track", label: "Rel utama (main line)", source: "openrailwaymap", swatch: "track" },
  { id: "siding", label: "siding (rel sampang)", source: "openrailwaymap", swatch: "siding" },
  { id: "yard", label: "yard / emplacement", source: "openrailwaymap", swatch: "yard" },
  { id: "switch", label: "wissel (wesel)", source: "openrailwaymap", swatch: "switch" },
  { id: "crossover", label: "kruiswissel (wesel silang)", source: "openrailwaymap", swatch: "crossover" },
  {
    id: "maxspeed",
    label: "Angka di rel = maks. kecepatan teknis (maxspeed) — bukan Gapeka",
    source: "openrailwaymap",
    swatch: "maxspeed",
  },
  {
    id: "speed-signal",
    label: "Sinyal kecepatan (speed signal)",
    source: "openrailwaymap",
    swatch: "speed-signal",
  },
  { id: "bridge", label: "Jembatan / terowongan", source: "openrailwaymap", swatch: "bridge" },
];

export function isOverlayActive(overlay: OverlayId): boolean {
  return overlay !== OVERLAYS.default;
}

/** The provenance note, printed above the rows. */
export function legendSummary(overlay: OverlayId): string {
  if (!isOverlayActive(overlay)) return "";
  const name = overlay === "infrastruktur" ? "Infrastruktur" : "Max Speed";
  return (
    `Overlay ${name} dari data komunitas OpenStreetMap / OpenRailwayMap ` +
    `(tag railway=* untuk infrastruktur, maxspeed=* untuk kecepatan teknis). ` +
    `Ini bukan data Gapeka: kecepatan maksimum menurut Gapeka tercetak di ` +
    `kolom Kecepatan Maksimum timetable PDF.`
  );
}

const SWATCH_CLASS: Record<LegendRow["swatch"], string> = {
  track: "bg-neutral-800",
  siding: "bg-neutral-500",
  yard: "bg-neutral-400",
  switch: "bg-amber-500",
  crossover: "bg-amber-700",
  maxspeed: "bg-blue-600",
  "speed-signal": "bg-emerald-500",
  bridge: "bg-violet-500",
};

export function OverlayLegend(props: {
  readonly overlay: OverlayId;
  readonly onClose: () => void;
}): React.ReactElement | null {
  const [collapsed, setCollapsed] = useState(false);

  if (!isOverlayActive(props.overlay)) return null;

  return (
    <aside
      aria-label="Legenda overlay rel"
      className="pointer-events-auto absolute bottom-24 z-20 w-56 max-w-[80vw] overflow-hidden rounded-2xl border border-black/10 bg-white/95 shadow-lg backdrop-blur sm:bottom-20 sm:left-3"
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <TrainTrack size={14} aria-hidden="true" className="shrink-0 text-neutral-500" />
          <h2 className="truncate text-[12.5px] font-bold text-neutral-900">
            Legenda {props.overlay === "infrastruktur" ? "Infrastruktur" : "Max Speed"}
          </h2>
        </div>
        <button
          type="button"
          aria-label={collapsed ? "Tampilkan legenda" : "Sembunyikan legenda"}
          aria-expanded={!collapsed}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={() => setCollapsed((value) => !value)}
        >
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={`transition-transform duration-150 ${collapsed ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {collapsed ? null : (
        <div className="max-h-64 overflow-y-auto overscroll-contain px-3 py-2">
          <p className="mb-2 text-[11.5px] leading-relaxed text-neutral-600">
            {legendSummary(props.overlay)}
          </p>
          <ul className="space-y-1.5">
            {LEGEND_ROWS.map((row) => (
              <li key={row.id} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`inline-block h-2.5 w-5 shrink-0 rounded-sm ${SWATCH_CLASS[row.swatch]}`}
                />
                <span className="min-w-0 text-[12px] leading-snug break-words text-neutral-700">
                  {row.label}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-black/5 pt-1.5 text-[11px] text-neutral-500">
            Garis abu-abu tebal = rel menurut Gapeka (391 segmen). Warna lain dari overlay
            hanya konteks infrastruktur.
          </p>
        </div>
      )}
    </aside>
  );
}
