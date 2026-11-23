/**
 * Clean, compact floating controls for the map.
 *
 * Rules followed:
 * - icon buttons always carry `aria-label`;
 * - `<button>` for actions, never a clickable `<div>`;
 * - `focus-visible:ring-*` everywhere, never bare `outline-none`;
 * - no `transition: all` — properties are listed;
 * - `Plus Jakarta Sans` + `tabular-nums` on every live number.
 */
import { useEffect, useRef } from "react";
import {
  ChevronDown,
  Info,
  Layers,
  Pause,
  Play,
  Search,
  SlidersHorizontal,
  TrainTrack,
  X,
} from "lucide-react";

export const buttonClass =
  "inline-flex h-10 items-center gap-2 rounded-full border border-black/10 bg-white/95 px-3.5 text-sm font-medium text-neutral-900 shadow-sm backdrop-blur transition-[background-color,color,transform] duration-150 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2";

export const iconButtonClass =
  "inline-flex h-10 w-10 items-center justify-center rounded-full border border-black/10 bg-white/95 text-neutral-700 shadow-sm backdrop-blur transition-[background-color,color,transform] duration-150 hover:bg-white hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2";

export function SearchPill(props: {
  readonly query: string;
  readonly onChange: (value: string) => void;
  readonly onClear: () => void;
  readonly inputRef?: React.RefObject<HTMLInputElement | null>;
}): React.ReactElement {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-black/10 bg-white/95 py-1 pr-1 pl-3.5 shadow-sm backdrop-blur focus-within:ring-2 focus-within:ring-blue-600">
      <Search size={17} aria-hidden="true" className="shrink-0 text-neutral-500" />
      <label htmlFor="search" className="sr-only">
        Cari KA, nama kereta atau stasiun
      </label>
      <input
        id="search"
        ref={props.inputRef}
        type="search"
        autoComplete="off"
        spellCheck={false}
        placeholder="Cari KA 249, Gajayana, Gambir…"
        value={props.query}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-9 min-w-0 flex-1 bg-transparent text-sm text-neutral-900 placeholder:text-neutral-400 focus:outline-none"
      />
      {props.query.length > 0 ? (
        <button
          type="button"
          aria-label="Hapus pencarian"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          onClick={props.onClear}
        >
          <X size={15} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

export function StatusPill(props: {
  readonly mode: "live" | "sim";
  readonly label: string;
  readonly dateLabel: string;
  readonly activeCount: number;
  readonly snapshotReady: boolean;
  readonly error: string | null;
}): React.ReactElement {
  const live = props.mode === "live";
  return (
    <div
      aria-live="polite"
      className="flex items-center gap-2 rounded-full border border-black/10 bg-white/95 py-2 pr-3.5 pl-3 shadow-sm backdrop-blur"
    >
      <span
        aria-hidden="true"
        className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
          live ? "animate-pulse bg-emerald-500" : "bg-amber-500"
        }`}
      />
      <span className="text-[13px] font-semibold whitespace-nowrap text-neutral-900 tabular-nums">
        {props.label}
      </span>
      <span className="hidden text-[12px] whitespace-nowrap text-neutral-500 tabular-nums sm:inline">
        {props.dateLabel}
      </span>
      <span className="text-[12px] font-medium whitespace-nowrap text-neutral-700 tabular-nums">
        {props.snapshotReady ? `${props.activeCount} KA` : "…"}
      </span>
      {props.error ? (
        <span
          className="text-[12px] font-medium text-amber-700"
          title={props.error}
        >
          <span className="sr-only">Peringatan peta: </span>
          Sebagian layer peta belum termuat
        </span>
      ) : null}
    </div>
  );
}

export function LayersPopover(props: {
  readonly open: boolean;
  readonly basemap: string;
  readonly overlay: string;
  readonly onBasemap: (basemap: import("../map/sources").BasemapId) => void;
  readonly onOverlay: (overlay: import("../map/sources").OverlayId) => void;
  readonly onClose: () => void;
  readonly triggerRef?: React.RefObject<HTMLButtonElement | null>;
}): React.ReactElement | null {
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!props.open) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") props.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [props.onClose, props.open]);

  if (!props.open) return null;

  const radio = (
    name: string,
    value: string,
    checked: boolean,
    label: string,
    onChange: () => void,
  ): React.ReactElement => (
    <label
      key={value}
      className="flex min-h-10 cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-neutral-800 transition-colors hover:bg-neutral-50 has-checked:bg-blue-50 has-focus-visible:ring-2 has-focus-visible:ring-blue-600"
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 shrink-0 accent-blue-700"
      />
      <span className="font-medium">{label}</span>
    </label>
  );

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Lapisan peta"
      className="absolute top-12 right-0 z-10 w-64 rounded-2xl border border-black/10 bg-white p-3 shadow-lg"
    >
      <div className="mb-1 flex items-center gap-2 px-1 text-[12px] font-semibold tracking-wide text-neutral-500 uppercase">
        <Layers size={13} aria-hidden="true" />
        Peta Dasar
      </div>
      <div className="mb-3">
        {radio("basemap", "positron", props.basemap === "positron", "Clean (Positron)", () =>
          props.onBasemap("positron"),
        )}
        {radio("basemap", "liberty", props.basemap === "liberty", "Detail (Liberty)", () =>
          props.onBasemap("liberty"),
        )}
      </div>
      <div className="mb-1 flex items-center gap-2 px-1 text-[12px] font-semibold tracking-wide text-neutral-500 uppercase">
        <TrainTrack size={13} aria-hidden="true" />
        Overlay Rel
      </div>
      <div>
        {radio("overlay", "default", props.overlay === "default", "Default", () =>
          props.onOverlay("default"),
        )}
        {radio("overlay", "infrastruktur", props.overlay === "infrastruktur", "Infrastruktur", () =>
          props.onOverlay("infrastruktur"),
        )}
        {radio("overlay", "maxspeed", props.overlay === "maxspeed", "Max Speed", () =>
          props.onOverlay("maxspeed"),
        )}
      </div>
      {props.overlay !== "default" ? (
        <p className="mt-3 rounded-xl bg-neutral-50 px-3 py-2 text-[12px] leading-relaxed text-neutral-600">
          Overlay dari data komunitas OpenStreetMap / OpenRailwayMap (tag
          <code className="font-mono text-[11px]"> railway=* / maxspeed=* </code>
          ). Ini berbeda dari kecepatan maksimum yang tercetak di Gapeka.
        </p>
      ) : null}
    </div>
  );
}

export function FilterButton(props: {
  readonly active: boolean;
  readonly onToggle: () => void;
}): React.ReactElement {
  return (
    <button
      type="button"
      aria-label="Tampilkan KA fakultatif"
      aria-pressed={props.active}
      title="Tampilkan KA fakultatif"
      className={`${iconButtonClass} ${props.active ? "border-amber-600/40 bg-amber-50 text-amber-700" : ""}`}
      onClick={props.onToggle}
    >
      <SlidersHorizontal size={18} aria-hidden="true" />
    </button>
  );
}

export function AboutButton(props: { readonly onOpen: () => void }): React.ReactElement {
  return (
    <button
      type="button"
      aria-label="Tentang aplikasi ini"
      title="Tentang"
      className={iconButtonClass}
      onClick={props.onOpen}
    >
      <Info size={18} aria-hidden="true" />
    </button>
  );
}

export function LayersButton(props: {
  readonly onToggle: () => void;
  readonly buttonRef?: React.RefObject<HTMLButtonElement | null>;
}): React.ReactElement {
  return (
    <button
      ref={props.buttonRef}
      type="button"
      aria-label="Lapisan peta"
      aria-haspopup="dialog"
      title="Lapisan"
      className={iconButtonClass}
      onClick={props.onToggle}
    >
      <Layers size={18} aria-hidden="true" />
    </button>
  );
}

export function FollowButton(props: {
  readonly label: string;
  readonly onPress: () => void;
}): React.ReactElement {
  return (
    <button type="button" className={buttonClass} onClick={props.onPress}>
      {props.label}
    </button>
  );
}

export function PlayPauseButton(props: {
  readonly playing: boolean;
  readonly onToggle: () => void;
}): React.ReactElement {
  return (
    <button
      type="button"
      aria-label={props.playing ? "Jeda" : "Putar"}
      title={props.playing ? "Jeda" : "Putar"}
      className={iconButtonClass}
      onClick={props.onToggle}
    >
      {props.playing ? (
        <Pause size={17} aria-hidden="true" />
      ) : (
        <Play size={17} aria-hidden="true" />
      )}
    </button>
  );
}

export function ChevronToggle(props: {
  readonly label: string;
  readonly open: boolean;
  readonly onToggle: () => void;
}): React.ReactElement {
  return (
    <button
      type="button"
      aria-expanded={props.open}
      className="mt-2 inline-flex items-center gap-1 text-[13px] font-medium text-blue-700 transition-colors hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 rounded-lg px-1 py-0.5"
      onClick={props.onToggle}
    >
      {props.label}
      <ChevronDown
        size={15}
        aria-hidden="true"
        className={`transition-transform duration-150 ${props.open ? "rotate-180" : ""}`}
      />
    </button>
  );
}
