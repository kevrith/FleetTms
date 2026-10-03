/**
 * The remote engine immobiliser's safety rules (masterplan 5.28): stopping an engine is only allowed when the vehicle is known to be
 * standing or crawling right now. Mirrored by apps/api/app/immobiliser_rules.py and tested against immobiliser-cases.json.
 */

export const IMMOBILISER_MAX_SPEED_KMH = 5;
export const IMMOBILISER_MAX_POSITION_AGE_S = 180;

export const IMMOBILISER_REASONS: Record<string, string> = {
  moving:
    "The vehicle is moving. The engine can only be stopped when it is standing or going very slowly.",
  stale_position:
    "The vehicle has not reported its position in the last three minutes, so we cannot tell it is stopped.",
  no_position: "The vehicle has never reported a position.",
  offline: "The tracker is offline, so it cannot receive the command.",
  unsupported: "This tracker does not support remote engine stop.",
};

export function immobiliserCheck(input: {
  action: "immobilise" | "release";
  speed_kmh: number | null;
  position_age_s: number | null;
  online: boolean;
  supported: boolean;
}): { allowed: boolean; reason: string | null } {
  if (!input.supported) return { allowed: false, reason: "unsupported" };
  if (input.action === "release") return { allowed: true, reason: null };
  if (!input.online) return { allowed: false, reason: "offline" };
  if (input.position_age_s === null) return { allowed: false, reason: "no_position" };
  if (input.position_age_s > IMMOBILISER_MAX_POSITION_AGE_S)
    return { allowed: false, reason: "stale_position" };
  if ((input.speed_kmh ?? 0) > IMMOBILISER_MAX_SPEED_KMH)
    return { allowed: false, reason: "moving" };
  return { allowed: true, reason: null };
}
