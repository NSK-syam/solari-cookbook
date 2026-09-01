import { useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap, Marker as MapLibreMarker, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const MILTON_CENTER: [number, number] = [-75.31, 38.78];
const OSM_ATTRIBUTION = "© OpenStreetMap contributors";
const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: OSM_ATTRIBUTION,
    },
  },
  layers: [
    {
      id: "osm-basemap",
      type: "raster",
      source: "osm",
      paint: { "raster-saturation": -0.35, "raster-contrast": 0.12 },
    },
  ],
};

type MapStatus = "loading" | "ready" | "unavailable";

export function ApproximatePropertyMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<MapStatus>("loading");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof window.WebGLRenderingContext === "undefined") {
      setStatus("unavailable");
      return;
    }

    let mounted = true;
    let map: MapLibreMap | null = null;
    let marker: MapLibreMarker | null = null;
    let observer: ResizeObserver | null = null;

    const initialize = async () => {
      try {
        const { Map, Marker, NavigationControl } = await import("maplibre-gl");
        if (!mounted) return;
        map = new Map({
          container,
          style: OSM_STYLE,
          center: MILTON_CENTER,
          zoom: 12.8,
          minZoom: 10,
          maxZoom: 15,
          maxBounds: [[-75.55, 38.62], [-75.05, 38.95]],
          attributionControl: false,
          cooperativeGestures: true,
        });
        map.scrollZoom.disable();
        map.addControl(new NavigationControl({ showCompass: false }), "top-right");

        const markerElement = document.createElement("div");
        markerElement.className = "evidence-map-marker";
        markerElement.setAttribute("aria-hidden", "true");
        marker = new Marker({ element: markerElement, anchor: "center" })
          .setLngLat(MILTON_CENTER)
          .addTo(map);

        map.once("load", () => {
          if (mounted) setStatus("ready");
        });

        if (typeof ResizeObserver !== "undefined") {
          observer = new ResizeObserver(() => map?.resize());
          observer.observe(container);
        }
      } catch {
        if (mounted) setStatus("unavailable");
      }
    };

    void initialize();

    return () => {
      mounted = false;
      observer?.disconnect();
      marker?.remove();
      map?.remove();
    };
  }, []);

  return (
    <section
      className={`spatial-stage real-evidence-map ${status}`}
      role="region"
      aria-label="Interactive real map of an approximate synthetic case area near Milton, Delaware"
      aria-describedby="synthetic-map-disclosure"
      data-map-status={status}
    >
      <div className="evidence-map-canvas" ref={containerRef} aria-hidden="true" />
      <div className="map-live-badge"><i aria-hidden="true" />REAL OPENSTREETMAP BASEMAP</div>
      <div className="coordinate-label">
        <span>APPROXIMATE CASE AREA</span>
        <strong>MILTON, DELAWARE</strong>
        <small id="synthetic-map-disclosure">Synthetic demonstration · exact parcel not displayed</small>
      </div>
      {status === "unavailable" && <p className="map-fallback">Live map unavailable · approximate area retained</p>}
      <a
        className="map-attribution"
        href="https://www.openstreetmap.org/copyright"
        target="_blank"
        rel="noopener noreferrer"
      >
        {OSM_ATTRIBUTION}
      </a>
    </section>
  );
}
