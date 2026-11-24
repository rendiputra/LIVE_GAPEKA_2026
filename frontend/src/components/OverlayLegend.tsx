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
  readonly swatch: string;
}

/**
 * OpenRailwayMap's `standard` style: line hierarchy and operating state.
 * These rows describe INFRASTRUCTURE, so they must never be shown while the
 * `maxspeed` overlay is active.
 */
export const INFRA_ROWS: readonly LegendRow[] = [
  { id: "main-track", label: "Rel utama (main line)", swatch: "bg-neutral-800" },
  { id: "branch", label: "Rel cabang / sekunder", swatch: "bg-neutral-500" },
  { id: "siding", label: "Siding / yard", swatch: "bg-neutral-400" },
  { id: "disused", label: "Nonaktif / konstruksi", swatch: "bg-neutral-300" },
  { id: "switch", label: "Wesel (wissel) & sinyal", swatch: "bg-amber-500" },
];

/**
 * OpenRailwayMap's `maxspeed` style: the colour bands it renders for the
 * `maxspeed` tag. These describe a TECHNICAL line speed from OSM, which is a
 * different quantity from the maximum speed printed in the Gapeka timetable.
 */
export const SPEED_ROWS: readonly LegendRow[] = [
  { id: "speed-0-40", label: "< 40 km/j", swatch: "bg-violet-700" },
  { id: "speed-40-60", label: "40–60 km/j", swatch: "bg-blue-700" },
  { id: "speed-60-80", label: "60–80 km/j", swatch: "bg-sky-500" },
  { id: "speed-80-120", label: "80–120 km/j", swatch: "bg-emerald-600" },
  { id: "speed-120-160", label: "120–160 km/j", swatch: "bg-yellow-400" },
  { id: "speed-160-200", label: "160–200 km/j", swatch: "bg-orange-500" },
  { id: "speed-200-plus", label: "> 200 km/j", swatch: "bg-red-600" },
  { id: "speed-untagged", label: "Abu-abu: belum ada tag maxspeed", swatch: "bg-neutral-300" },
];

export function legendRows(overlay: OverlayId): readonly LegendRow[] {
  return overlay === "maxspeed" ? SPEED_ROWS : INFRA_ROWS;
}

export function isOverlayActive(overlay: OverlayId): boolean {
  return overlay !== OVERLAYS.default;
}

/** One concise provenance line, above the rows. */
export function legendSummary(overlay: OverlayId): string {
  if (!isOverlayActive(overlay)) return "";
  const name = overlay === "infrastruktur" ? "Infrastruktur" : "Max Speed";
  return (
    `Overlay ${name} dari data komunitas OpenStreetMap / OpenRailwayMap. ` +
    `Bukan data Gapeka: kecepatan cetak Gapeka ada di kolom Kecepatan ` +
    `Maksimum pada timetable PDF.`
  );
}

export function OverlayLegend(props: {
  readonly overlay: OverlayId;
  readonly onClose: () => void;
}): React.ReactElement | null {
  const [collapsed, setCollapsed] = useState(false);

  if (!isOverlayActive(props.overlay)) return null;

  return (
    <aside
      aria-label="Legenda overlay rel"
      className="pointer-events-auto w-56 max-w-[80vw] overflow-hidden rounded-2xl border border-black/10 bg-white/95 shadow-lg backdrop-blur"
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
        <div className="px-3 py-2">
          <p className="mb-2 text-[11.5px] leading-relaxed text-neutral-600">
            {legendSummary(props.overlay)}
          </p>
          <ul className="space-y-1.5">
            {legendRows(props.overlay).map((row) => (
              <li key={row.id} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`inline-block h-2.5 w-5 shrink-0 rounded-sm ${row.swatch}`}
                />
                <span className="min-w-0 text-[12px] leading-snug break-words text-neutral-700">
                  {row.label}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-black/5 pt-1.5 text-[11px] text-neutral-500">
            Rel Gapeka sendiri digambar sebagai garis abu-abu tipis (391 segmen).
          </p>
        </div>
      )}
    </aside>
  );
}
