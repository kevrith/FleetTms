import type { Role } from "@fleettms/types";

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  manager: "Manager",
  supervisor: "Supervisor",
  accountant: "Accountant",
  driver: "Driver",
  turnboy: "Turnboy / Assistant",
  workshop: "Workshop / Storekeeper",
  lessor: "Vehicle owner (lessor)",
};

/** Roles that sign in with a phone number and one-time code (masterplan Section 10). */
export const OTP_ONLY_ROLES: readonly Role[] = ["driver", "turnboy"];

export const isOtpOnly = (roles: readonly Role[]): boolean =>
  roles.length > 0 && roles.every((r) => OTP_ONLY_ROLES.includes(r));

export type HomeView = "owner" | "driver";

/**
 * Owner-driver mode (masterplan Section 3): someone who is both a business role and a driver
 * can switch between the Owner view and the Driver view. Everyone else has exactly one view.
 */
export function availableViews(roles: readonly Role[]): HomeView[] {
  const business = roles.some((r) => !OTP_ONLY_ROLES.includes(r));
  const driver = roles.includes("driver");
  if (business && driver) return ["owner", "driver"];
  return driver || roles.every((r) => r === "turnboy") ? ["driver"] : ["owner"];
}

export const defaultView = (roles: readonly Role[]): HomeView =>
  availableViews(roles)[0] ?? "owner";
