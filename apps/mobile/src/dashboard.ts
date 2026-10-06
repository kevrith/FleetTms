import type { DashboardAlert, DashboardFleet } from "@fleettms/types";

/** How many alerts the owner sees before tapping "See all". */
export const ALERTS_SHOWN = 3;

/** Whole shillings for a tile: "KES 12,500". The cents belong on the web statements, not on a glance. */
export function kesShort(cents: number): string {
  const kes = Math.round(Math.abs(cents) / 100);
  return `${cents < 0 ? "-" : ""}KES ${kes.toLocaleString("en-KE")}`;
}

/** "just now", "5 min ago", "2 h ago", "3 days ago". */
export function ago(from: Date | string | number, now: Date | number): string {
  const seconds = Math.max(0, (+new Date(now) - +new Date(from)) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  const days = Math.round(seconds / 86400);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** The phone tab that shows what a web link points at, or null when that part of the business is only on the web. */
export function tabForLink(link: string): string | null {
  if (link === "/map" || link.startsWith("/tracking")) return "Map";
  if (link.startsWith("/vehicles")) return "Vehicles";
  if (link.startsWith("/workshop")) return "Workshop";
  if (link.startsWith("/expenses")) return "Money";
  return null;
}

/** What the owner sees of the alerts: emergencies have their own banner, the rest are cut to the first few unless asked for all. */
export function visibleAlerts(
  alerts: DashboardAlert[],
  showAll: boolean,
): { shown: DashboardAlert[]; hidden: number; urgent: number; watch: number } {
  const rest = alerts.filter((a) => !a.emergency);
  const shown = showAll ? rest : rest.slice(0, ALERTS_SHOWN);
  const urgent = rest.filter((a) => a.severity === "red").length;
  return { shown, hidden: rest.length - shown.length, urgent, watch: rest.length - urgent };
}

const FLEET_ORDER: [keyof DashboardFleet, string][] = [
  ["moving", "moving"],
  ["idle", "standing"],
  ["offline", "not reporting"],
  ["in_workshop", "in the workshop"],
  ["parked", "parked"],
  ["unknown", "never seen"],
];

/** "6 moving · 2 standing · 1 in the workshop"; states with no lorries are left out. */
export function fleetLine(fleet: DashboardFleet): string {
  const parts = FLEET_ORDER.filter(([key]) => fleet[key] > 0).map(([key, label]) => `${fleet[key]} ${label}`);
  return parts.length ? parts.join(" · ") : "No active lorries";
}

/** "3 running · 5 done" for the trips tile. */
export function tripsLine(active: number, done: number): string {
  return `${active} running · ${done} done`;
}
