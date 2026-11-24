/**
 * The MapLibre map: every entity rendered in WebGL, never React DOM.
 *
 * The frames it draws come from the Web Worker (the ADR 011 design); this
 * component only receives GeoJSON and writes it into the sources. Position
 * maths never runs here.
 */
import { useCallback, useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  BASEMAPS,
  buildTileSource,
  styleLayers,
  type BasemapId,
  type OverlayId,
} from "./sources";
import {
  railNetworkGeoJSON,
  routeGeoJSON,
  stationsGeoJSON,
} from "./layers";
import type { ScheduleSnapshot, TrainPosition } from "../engine/types";
import type { PositionsFeatureCollection } from "../worker/geojson";

export interface MapStatus {
  readonly status: "loading" | "ready" | "error";
  readonly error: string | null;
}

export interface LiveMapProps {
  readonly snapshot: ScheduleSnapshot | null;
  readonly selectedTripId: string | null;
  readonly basemap: BasemapId;
  readonly overlay: OverlayId;
  readonly trains: PositionsFeatureCollection | null;
  readonly follow: boolean;
  readonly onTrainClick: (tripId: string) => void;
  readonly onStationClick: (code: string) => void;
  readonly onTilesError: (message: string) => void;
  readonly onStatus: (status: MapStatus) => void;
  readonly onDrag?: () => void;
  /**
   * Called with the map instance once the map is constructed and again when it
   * is torn down. The app uses it for pan-to requests without a window global.
   */
  readonly onInstance?: (map: maplibregl.Map | null) => void;
}

function setData(
  map: maplibregl.Map,
  sourceId: string,
  data: Parameters<maplibregl.GeoJSONSource["setData"]>[0],
): void {
  const source = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
  if (source) source.setData(data as never);
}

const property = <T,>(features: readonly T[] | undefined) => features?.[0];

/**
 * Push the rail network into its source and record how many segments it holds.
 *
 * `data-rail-features` on the map container is read-only observability: it lets
 * the end-to-end suite assert that the geometry actually reached MapLibre on a
 * cold load (a canvas pixel probe cannot, because MapLibre renders without
 * `preserveDrawingBuffer`), and it is useful in support when someone reports
 * "no rail lines".
 */
/**
 * Visible-map padding for camera moves.
 *
 * On a phone the bottom-anchored inspector card covers the lower part of the
 * map, so centring a train without padding puts it behind the card. Padding
 * shifts the camera target up into the window the user can actually see.
 */
export function cameraPadding(): { top: number; bottom: number } {
  return window.matchMedia("(min-width: 1024px)").matches
    ? { top: 0, bottom: 0 }
    : { top: 120, bottom: 320 };
}

/**
 * Collapse MapLibre's attribution on a phone.
 *
 * The control is a native `<details>` element and `_updateCompact()` opens it on
 * first paint (`open` attribute plus `compact-show` class), printing the full
 * licence line across the bottom of a 390px screen.
 *
 * Collapsing means REMOVING `open` — the opposite of setting it — and dropping
 * `compact-show`. No MutationObserver: it fought the user's tap. MapLibre
 * rebuilds the attribution when source data arrives and re-opens it, so the
 * collapse is also re-applied on those events, and stops for good once the user
 * taps (i) so the native toggle owns the state from then on.
 */
function collapseAttributionOnMobile(map: maplibregl.Map): void {
  if (!window.matchMedia("(max-width: 767px)").matches) return;
  const attribution = map.getContainer().querySelector<HTMLElement>(".maplibregl-ctrl-attrib");
  if (!attribution) return;
  attribution.removeAttribute("open");
  attribution.classList.remove("maplibregl-compact-show");
}

function pushRail(map: maplibregl.Map, snapshot: ScheduleSnapshot): void {
  const data = railNetworkGeoJSON(snapshot.trips);
  setData(map, "gapeka-rail", data as never);
  map.getContainer().dataset.railFeatures = String(data.features.length);
}

export function LiveMap(props: LiveMapProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const propsRef = useRef(props);
  propsRef.current = props;
  const readyRef = useRef(false);
  const styleLoadedRef = useRef(false);

  const addLayers = useCallback((map: maplibregl.Map): void => {
    const snapshot = propsRef.current.snapshot;
    const overlay = propsRef.current.overlay;

    const addSource = (id: string, source: maplibregl.SourceSpecification): void => {
      if (!map.getSource(id)) map.addSource(id, source);
    };

    addSource("gapeka-rail", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    addSource("gapeka-route", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    addSource("gapeka-stations", {
      type: "geojson",
      data: snapshot
        ? (stationsGeoJSON(snapshot.stations.values()) as never)
        : { type: "FeatureCollection", features: [] },
    });
    addSource("gapeka-trains", {
      type: "geojson",
      data: propsRef.current.trains ?? { type: "FeatureCollection", features: [] },
    });
    addSource("gapeka-selected", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    const overlaySource = buildTileSource(overlay);
    if (overlaySource) {
      addSource("gapeka-overlay", {
        type: "raster",
        tiles: [...overlaySource.tiles],
        tileSize: overlaySource.tileSize,
        attribution: overlaySource.attribution,
      });
    }

    // The source is created empty above; if the schedule is already loaded,
    // fill it in the same pass so the first paint is complete.
    if (snapshot) pushRail(map, snapshot);

    for (const layer of styleLayers()) {
      if (map.getLayer(layer.id)) continue;
      // The overlay raster needs its source; every other layer does. Adding
      // a raster layer before its source exists throws, and a caught throw
      // would silently drop everything below it too.
      if (layer.id === "gapeka-overlay" && !map.getSource(layer.source)) continue;
      try {
        map.addLayer(layer as never);
      } catch (error) {
        // Glyph or style errors during addLayer must not take the whole map
        // down, but they are NOT swallowed silently: ask the operator.
        console.warn(`[LiveMap] addLayer ${layer.id} failed:`, error);
      }
    }
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    const map = new maplibregl.Map({
      container,
      style: BASEMAPS.options.find((basemap) => basemap.id === propsRef.current.basemap)!
        .style,
      center: [110.35, -7.15],
      zoom: 7.2,
      attributionControl: false,
      fadeDuration: 100,
    });
    mapRef.current = map;
    propsRef.current.onInstance?.(map);
    propsRef.current.onStatus({ status: "loading", error: null });

    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
    collapseAttributionOnMobile(map);

    // MapLibre rebuilds and re-opens the attribution when source data arrives
    // (~250 ms after load), so re-collapse on its own data events; stop once the
    // user taps (i), after which the native <details> toggle owns the state.
    let userToggledAttribution = false;
    const attributionButton = map
      .getContainer()
      .querySelector<HTMLElement>(".maplibregl-ctrl-attrib-button");
    const markUserToggled = (): void => {
      userToggledAttribution = true;
    };
    attributionButton?.addEventListener("click", markUserToggled);
    const onMapData = (): void => {
      if (!userToggledAttribution) collapseAttributionOnMobile(map);
    };
    map.on("data", onMapData);

    map.on("error", (event: maplibregl.ErrorEvent) => {
      // Surface the raw message for diagnosis: a validation error in a symbol
      // layout, a missing source, or a bad beforeId all arrive here, and the
      // previous behaviour swallowed them all as a generic tile warning.
      console.error(`[LiveMap] map error:`, event.error?.message ?? event);
      // Tile 404s are routine, but they are not fatal: the map keeps the
      // trains it CAN draw.
      const message = event.error?.message ?? "";
      if (!message) return;
      propsRef.current.onTilesError(message);
    });

    map.once("style.load", () => {
      styleLoadedRef.current = true;
      addLayers(map);
      readyRef.current = true;
      propsRef.current.onStatus({ status: "ready", error: null });
      collapseAttributionOnMobile(map);
    });

    map.on("click", "gapeka-trains", (event) => {
      const feature = property(event.features);
      const tripId = feature?.properties?.tripId;
      if (typeof tripId === "string") propsRef.current.onTrainClick(tripId);
    });
    map.on("click", "gapeka-station-hubs", (event) => {
      const feature = property(event.features);
      const code = feature?.properties?.code;
      if (typeof code === "string") propsRef.current.onStationClick(code);
    });
    map.on("click", "gapeka-station-regionals", (event) => {
      const feature = property(event.features);
      const code = feature?.properties?.code;
      if (typeof code === "string") propsRef.current.onStationClick(code);
    });

    for (const layerId of [
      "gapeka-trains",
      "gapeka-station-hubs",
      "gapeka-station-regionals",
    ]) {
      map.on("mouseenter", layerId, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", layerId, () => {
        map.getCanvas().style.cursor = "";
      });
    }

    return () => {
      map.off("data", onMapData);
      attributionButton?.removeEventListener("click", markUserToggled);
      propsRef.current.onInstance?.(null);
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
      styleLoadedRef.current = false;
    };
  }, [addLayers]);

  // Basemap switches rebuild the style; overlay switches do not. A setStyle
  // replaces the whole layer list, so layers must be re-wired on the new
  // style's load event, and re-wiring is driven by `styleLoadedRef` (false
  // until the new style is ready).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleLoadedRef.current) return;
    const style = BASEMAPS.options.find((basemap) => basemap.id === props.basemap)!.style;
    const current = map.getStyle();
    if (current && (current as { name?: string }).name === style) return;
    styleLoadedRef.current = false;
    map.setStyle(style);
    map.once("style.load", () => {
      styleLoadedRef.current = true;
      addLayers(map);
    });
  }, [props.basemap, props.overlay, addLayers]);

  // Overlay toggle without rebuilding the basemap. The overlay must sit BELOW
  // the Gapeka rail and the stations; appending it without a beforeId would
  // put it on top of everything, including the trains.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const overlaySource = buildTileSource(props.overlay);
    const exists = Boolean(map.getSource("gapeka-overlay"));
    if (overlaySource && !exists) {
      map.addSource("gapeka-overlay", {
        type: "raster",
        tiles: [...overlaySource.tiles],
        tileSize: overlaySource.tileSize,
        attribution: overlaySource.attribution,
      });
      const layer = styleLayers().find((entry) => entry.id === "gapeka-overlay");
      if (layer && !map.getLayer("gapeka-overlay")) {
        // Insert before the station layers so our own geometry stays on top.
        map.addLayer(layer as never, "gapeka-station-hubs");
      }
      return;
    }
    if (!overlaySource && exists) {
      map.removeLayer("gapeka-overlay");
      map.removeSource("gapeka-overlay");
    }
  }, [props.overlay]);

  // The rail network arrives AFTER the map is ready: the style loads from the
  // network in a few hundred ms, while the 1.1 MB schedule payload is still in
  // flight, so `addLayers` creates `gapeka-rail` with an empty collection. No
  // effect used to push the geometry once the snapshot landed, which is why the
  // 391 segments were invisible until an overlay toggle forced a
  // setStyle -> style.load -> addLayers cycle. Push it here instead.
  useEffect(() => {
    const map = mapRef.current;
    const snapshot = props.snapshot;
    if (!map || !snapshot) return;
    pushRail(map, snapshot);
  }, [props.snapshot]);

  // Selected route highlight.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const snapshot = props.snapshot;
    if (!snapshot || !props.selectedTripId) {
      setData(map, "gapeka-route", { type: "FeatureCollection", features: [] });
      return;
    }
    const trip = snapshot.trips.find((entry) => entry.tripId === props.selectedTripId);
    if (!trip) return;
    setData(map, "gapeka-route", routeGeoJSON(trip.segments, trip.tripId) as never);
  }, [props.snapshot, props.selectedTripId]);

  // Trains from the worker, written straight into the source. No React render.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current || !props.trains) return;
    setData(map, "gapeka-trains", props.trains as never);

    const selected = props.selectedTripId;
    const feature = selected
      ? props.trains.features.find((entry) => entry.id === selected)
      : null;
    setData(
      map,
      "gapeka-selected",
      feature
        ? {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                id: feature.id,
                geometry: feature.geometry,
                properties: { tripId: feature.id },
              },
            ],
          }
        : { type: "FeatureCollection", features: [] },
    );

    // Ikuti KA: keep the selected train centred at the telemetry rate. A drag
    // already reported a follow release upstream.
    if (props.follow && feature) {
      const target = feature.geometry.coordinates;
      map.easeTo({
        center: [target[0], target[1]],
        padding: cameraPadding(),
        duration: 350,
        essential: true,
      });
    }
  }, [props.trains, props.selectedTripId, props.follow]);

  // A drag releases follow mode.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const release = (): void => {
      if (props.follow) props.onDrag?.();
    };
    map.on("dragstart", release);
    return () => {
      map.off("dragstart", release);
    };
  }, [props.follow, props.onDrag]);

  return (
    <div
      ref={containerRef}
      data-testid="live-map"
      className="absolute inset-0 h-[100dvh] w-[100vw]"
      role="application"
      aria-label="Peta posisi estimasi kereta api"
    />
  );
}

export type { TrainPosition };
