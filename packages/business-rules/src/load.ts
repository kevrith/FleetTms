/**
 * Load compliance (masterplan 5.22): is the lorry overloaded? Mirrored by apps/api/app/load_rules.py and tested against
 * load-cases.json on both sides.
 */

export interface LoadInput {
  /** Net cargo weight from the weighbridge ticket. */
  cargo_kg: number;
  /** The lorry's own weight, if known. */
  tare_kg: number | null;
  /** Legal gross vehicle weight. */
  gvw_limit_kg: number | null;
  capacity_tonnes: number | null;
}

/** Kilograms over the limit (0 when within it), or null when there is nothing to judge the load against. */
export function overloadKg(input: LoadInput): number | null {
  if (input.gvw_limit_kg !== null && input.tare_kg !== null) {
    return Math.max(0, input.tare_kg + input.cargo_kg - input.gvw_limit_kg);
  }
  if (input.capacity_tonnes !== null) {
    return Math.max(0, input.cargo_kg - Math.round(input.capacity_tonnes * 1000));
  }
  return null;
}
