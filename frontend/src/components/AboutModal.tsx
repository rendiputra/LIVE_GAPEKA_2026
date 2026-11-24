/**
 * The "Tentang" modal: the full schedule and legal disclaimer lives here.
 *
 * ADR 002 amendment (2026-11-23): the frontend has neither a top preview banner
 * nor a persistent footer disclaimer bar. The estimate status is always on screen
 * in the status pill, and everything below is one click away.
 */
import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { Attribution } from "../engine/types";

export interface AboutModalProps {
  readonly open: boolean;
  readonly versionName: string | null;
  readonly effectiveFrom: string | null;
  readonly effectiveTo: string | null;
  readonly contentHash: string | null;
  readonly trips: number;
  readonly segments: number;
  readonly stations: number;
  readonly attribution: Attribution | null;
  readonly onClose: () => void;
}

export function AboutModal(props: AboutModalProps): React.ReactElement | null {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!props.open) return;
    // Remember what had focus so closing the dialog returns the user there.
    // Without this, focus falls back to <body> and keyboard users lose their
    // place entirely (WCAG 2.4.3 Focus Order).
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") props.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [props.open, props.onClose]);

  if (!props.open) return null;

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-end justify-center bg-neutral-950/40 p-4 backdrop-blur-[2px] sm:items-center"
      onClick={(event) => {
        if (event.target === event.currentTarget) props.onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        className="max-h-[86dvh] w-full max-w-lg overflow-y-auto overscroll-contain rounded-3xl bg-white p-6 shadow-xl"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="about-title" className="text-[17px] font-bold text-balance text-neutral-900">
              Tentang Gapeka 2026
            </h2>
            <p className="mt-0.5 text-[13px] text-neutral-500">
              {props.versionName ?? "Gapeka 2026"} · posisi estimasi, bukan posisi aktual
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="Tutup"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-neutral-500 transition-colors hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            onClick={props.onClose}
          >
            <X size={17} aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-4 text-[14px] leading-relaxed text-neutral-700">
          <section>
            <h3 className="mb-1 text-[13px] font-semibold tracking-wide text-neutral-900 uppercase">
              Disclaimer
            </h3>
            <p>
              {props.attribution?.disclaimer ??
                "Posisi estimasi berdasarkan jadwal Gapeka 2026, bukan posisi aktual. Diasumsikan tepat waktu dan beroperasi setiap hari."}
            </p>
            <p className="mt-1">
              {props.effectiveFrom
                ? `Jadwal berlaku resmi mulai ${formatDate(props.effectiveFrom)}.`
                : ""}{" "}
              {props.effectiveTo ? `Berlaku hingga ${formatDate(props.effectiveTo)}.` : ""}
            </p>
          </section>

          <section>
            <h3 className="mb-1 text-[13px] font-semibold tracking-wide text-neutral-900 uppercase">
              Data
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px] tabular-nums">
              <dt className="text-neutral-500">Versi</dt>
              <dd className="font-medium text-neutral-900">{props.versionName ?? "—"}</dd>
              <dt className="text-neutral-500">Berlaku mulai</dt>
              <dd className="font-medium text-neutral-900">
                {props.effectiveFrom ? formatDate(props.effectiveFrom) : "—"}
              </dd>
              <dt className="text-neutral-500">Hash data</dt>
              <dd className="font-mono text-[12px] font-medium break-all text-neutral-900">
                {props.contentHash ?? "—"}
              </dd>
              <dt className="text-neutral-500">Isi</dt>
              <dd className="font-medium text-neutral-900">
                {props.trips} perjalanan · {props.segments} segmen · {props.stations} stasiun
              </dd>
            </dl>
            <p className="mt-2 text-[13px] text-neutral-600">
              Kereta dengan tanda{" "}
              <span className="font-semibold text-amber-700">Estimasi kasar</span> memiliki
              keterangan tak bertime di PDF (mis. <code className="font-mono text-[12px]">Berh</code> /
              <code className="font-mono text-[12px]">Sb</code>); posisinya dihitung
              melintasi jeda yang lebih panjang, jadi ketepatannya lebih rendah.
            </p>
          </section>

          <section>
            <h3 className="mb-1 text-[13px] font-semibold tracking-wide text-neutral-900 uppercase">
              Atribusi peta
            </h3>
            <ul className="list-disc space-y-0.5 pl-4 text-[13px]">
              <li>
                {props.attribution?.osm ?? "© OpenStreetMap contributors"} (ODbL) —{" "}
                <a
                  className="rounded text-blue-700 underline underline-offset-2 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                  href="https://www.openstreetmap.org/copyright"
                  target="_blank"
                  rel="noreferrer"
                >
                  openstreetmap.org/copyright
                </a>
              </li>
              <li>
                Basemap vektor: OpenFreeMap
                <a
                  className="ml-1 rounded text-blue-700 underline underline-offset-2 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                  href="https://openfreemap.org/"
                  target="_blank"
                  rel="noreferrer"
                >
                  openfreemap.org
                </a>
              </li>
              <li>
                Overlay rel: OpenRailwayMap (CC-BY-SA 2.0)
                <a
                  className="ml-1 rounded text-blue-700 underline underline-offset-2 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                  href="https://www.openrailwaymap.org/"
                  target="_blank"
                  rel="noreferrer"
                >
                  openrailwaymap.org
                </a>
              </li>
            </ul>
          </section>

          <section>
            <h3 className="mb-1 text-[13px] font-semibold tracking-wide text-neutral-900 uppercase">
              Bukan afiliasi resmi
            </h3>
            <p className="text-[13px] text-neutral-600">
              Aplikasi ini bukan situs resmi PT Kereta Api Indonesia (Persero)
              maupun Kementerian Perhubungan. Jadwal Gapeka dapat berubah tanpa
              pemberitahuan; selalu konfirmasi perjalanan Anda melalui kanal resmi.
            </p>
          </section>

          <p className="rounded-xl bg-neutral-50 px-3 py-2 text-[13px] text-neutral-600">
            Model gerak <code className="font-mono text-[12px]">trapezoid_v1</code> adalah asumsi
            rekayasa, bukan data Gapeka: fase percepatan hanya di stasiun berhenti,
            dan kereta mencapai tepat Waktu Datang yang tercetak.
          </p>
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const months = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
  ];
  const month = Number(match[2]);
  return `${Number(match[3])} ${months[month] ?? month} ${match[1]}`;
}
