// Vitest setup: jsdom-less environment with the WebGL guard MapLibre needs.
//
// The map only runs in a browser (WebGL). Under Vitest we never construct a
// `Map`; this stub only exists so that importing maplibre-gl does not throw at
// module load time.

if (typeof globalThis.window === "undefined") {
  globalThis.window = globalThis as never;
}

// A minimal canvas/WebGL stub. MapLibre touches `getContext('webgl2')` when a
// Map is created; we never create one in tests, but some code paths import the
// module unconditionally.
const fakeCanvas = { getContext: () => null, style: {} };
if (typeof globalThis.document !== "undefined") {
  const originalCreateElement = document.createElement?.bind(document);
  if (originalCreateElement) {
    document.createElement = ((tag: string, options?: ElementCreationOptions) => {
      const element = originalCreateElement(tag, options);
      if (tag === "canvas") {
        (element as { getContext: () => null }).getContext = () => null;
        (element as unknown as { style: object }).style = {};
      }
      return element;
    }) as typeof document.createElement;
  }
  void fakeCanvas;
}
