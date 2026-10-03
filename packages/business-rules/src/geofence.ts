/**
 * Mapped areas (masterplan 5.12): is a position inside a circle or a polygon, and has a vehicle really entered or left. Mirrored by
 * apps/api/app/geofence_rules.py and tested against geofence-cases.json on both sides.
 */
import { haversineKm } from "./gps";

export const CONFIRM_FIXES = 2;

export type Shape =
  | { type: "circle"; lat: number; lng: number; radius_m: number }
  | { type: "polygon"; points: [number, number][] };

export const inCircle = (lat: number, lng: number, cLat: number, cLng: number, radiusM: number) =>
  haversineKm(lat, lng, cLat, cLng) * 1000 <= radiusM;

/** Ray casting over [lat, lng] corners. */
export function inPolygon(lat: number, lng: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0; i < ring.length; i++) {
    const [la1, ln1] = ring[i]!;
    const [la2, ln2] = ring[(i + 1) % ring.length]!;
    if (ln1 > lng !== ln2 > lng && lat < ((la2 - la1) * (lng - ln1)) / (ln2 - ln1) + la1)
      inside = !inside;
  }
  return inside;
}

export const insideShape = (shape: Shape, lat: number, lng: number) =>
  shape.type === "circle"
    ? inCircle(lat, lng, shape.lat, shape.lng, shape.radius_m)
    : inPolygon(lat, lng, shape.points);

export interface SideState {
  inside: boolean | null;
  pending: number;
}

/** One fix on: the first sighting sets the side with no event; a change of side must be seen twice in a row. */
export function geofenceStep(
  state: SideState | null,
  nowInside: boolean,
): { state: SideState; event: "enter" | "exit" | null } {
  const s = state ?? { inside: null, pending: 0 };
  if (s.inside === null) return { state: { inside: nowInside, pending: 0 }, event: null };
  if (nowInside === s.inside) return { state: { inside: s.inside, pending: 0 }, event: null };
  const pending = s.pending + 1;
  if (pending >= CONFIRM_FIXES)
    return { state: { inside: nowInside, pending: 0 }, event: nowInside ? "enter" : "exit" };
  return { state: { inside: s.inside, pending }, event: null };
}
