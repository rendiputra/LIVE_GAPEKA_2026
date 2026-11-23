/**
 * Placeholder shell for Milestone 1.
 *
 * The map, panels and Zustand stores arrive in later milestones; this file only
 * proves the Vite + React 19 + Tailwind v4 toolchain boots with self-hosted
 * fonts and zero CDN dependencies.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

function App() {
  return (
    <main className="grid min-h-full place-items-center bg-neutral-50 p-8 text-neutral-900">
      <div className="max-w-md space-y-2 text-center">
        <h1 className="font-semibold text-2xl tracking-tight">Gapeka 2026</h1>
        <p className="text-neutral-600 text-sm">
          Posisi estimasi berdasarkan jadwal Gapeka 2026, bukan posisi aktual.
        </p>
      </div>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
