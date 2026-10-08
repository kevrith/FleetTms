import type { GeofenceShape } from "@fleettms/types";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  colour: string;
  label: string;
  /** Draw it bigger (the one that is selected). */
  big?: boolean;
  /** A ring that pulses around it: an emergency, so it cannot be missed. */
  pulse?: boolean;
}

export interface MapLine {
  points: [number, number][];
  colour?: string;
}

/** A mapped area: a circle or a polygon, drawn under the markers. */
export interface MapShape {
  id: string;
  shape: GeofenceShape;
  colour: string;
  label: string;
  /** Draw it dashed (an area being drawn, not yet saved). */
  draft?: boolean;
}

const KENYA: [number, number] = [-0.4, 37.9];
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

/** A map of markers and lines. Tiles come from OpenStreetMap; the markers are drawn as circles so no image files are needed. */
export function MapView({
  markers,
  lines = [],
  shapes = [],
  draft = [],
  selected,
  onSelect,
  onMapClick,
  fitKey,
  height = 420,
}: {
  markers: MapMarker[];
  lines?: MapLine[];
  shapes?: MapShape[];
  /** Corners being clicked out, shown as an outline. */
  draft?: [number, number][];
  selected?: string | null;
  onSelect?: (id: string) => void;
  /** Called with where the map was clicked, to draw an area. */
  onMapClick?: (lat: number, lng: number) => void;
  /** Fit the view again when this changes (a different trip, a different area). */
  fitKey?: string;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef<string | null>(null);
  const clicked = useRef(onMapClick);
  clicked.current = onMapClick;

  useEffect(() => {
    if (!box.current || map.current) return;
    map.current = L.map(box.current, { zoomControl: true }).setView(KENYA, 6);
    L.tileLayer(TILES, {
      maxZoom: 18,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    map.current.on("click", (e: L.LeafletMouseEvent) =>
      clicked.current?.(e.latlng.lat, e.latlng.lng),
    );
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const g = layer.current;
    if (!g || !map.current) return;
    g.clearLayers();
    for (const line of lines) {
      if (line.points.length > 1)
        L.polyline(line.points, { color: line.colour ?? "#2563eb", weight: 4, opacity: 0.8 }).addTo(
          g,
        );
    }
    const bounds: [number, number][] = lines.flatMap((l) => l.points);
    for (const a of shapes) {
      const style = {
        color: a.colour,
        weight: 2,
        fillColor: a.colour,
        fillOpacity: 0.15,
        dashArray: a.draft ? "6 4" : undefined,
      };
      if (a.shape.type === "circle") {
        const c = L.circle([a.shape.lat, a.shape.lng], { ...style, radius: a.shape.radius_m });
        c.addTo(g).bindTooltip(a.label, { sticky: true });
        bounds.push(...circleBounds(a.shape.lat, a.shape.lng, a.shape.radius_m));
      } else {
        L.polygon(a.shape.points, style).addTo(g).bindTooltip(a.label, { sticky: true });
        bounds.push(...a.shape.points);
      }
    }
    if (draft.length > 0) {
      L.polyline(draft, { color: "#7c3aed", weight: 2, dashArray: "6 4" }).addTo(g);
      for (const c of draft)
        L.circleMarker(c, { radius: 4, color: "#7c3aed", fillOpacity: 1 }).addTo(g);
      bounds.push(...draft);
    }
    for (const m of markers) {
      if (m.pulse) {
        L.circleMarker([m.lat, m.lng], {
          radius: 22,
          stroke: false,
          fillColor: m.colour,
          fillOpacity: 0.35,
          className: "map-pulse",
          interactive: false,
        }).addTo(g);
      }
      const dot = L.circleMarker([m.lat, m.lng], {
        radius: m.big || m.id === selected ? 11 : 8,
        color: "#ffffff",
        weight: 2,
        fillColor: m.colour,
        fillOpacity: 1,
      }).addTo(g);
      dot.bindTooltip(m.label, { direction: "top" });
      if (onSelect) dot.on("click", () => onSelect(m.id));
      bounds.push([m.lat, m.lng]);
    }
    // Fit once to what there is; after that, leave the zoom where the person put it.
    if (fitted.current !== (fitKey ?? "") && bounds.length > 0) {
      map.current.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 14 });
      fitted.current = fitKey ?? "";
    }
  }, [markers, lines, shapes, draft, selected, onSelect, fitKey]);

  return (
    <div ref={box} style={{ height, width: "100%", borderRadius: 8 }} role="img" aria-label="Map" />
  );
}

/** The four compass points of a circle, so the map can be fitted around it. */
function circleBounds(lat: number, lng: number, radius: number): [number, number][] {
  const dLat = radius / 111320;
  const dLng = radius / (111320 * Math.max(Math.cos((lat * Math.PI) / 180), 0.01));
  return [
    [lat + dLat, lng],
    [lat - dLat, lng],
    [lat, lng + dLng],
    [lat, lng - dLng],
  ];
}
