/**
 * Quote pricing (masterplan 5.17): what a job should cost the client, what it should cost us, and the expected profit.
 * The API applies the same rules (apps/api/app/quote_rules.py); both are tested against quote-cases.json, so the
 * figures on the web preview and in a saved quote cannot drift apart.
 */

export type BillingMethod = "per_trip" | "per_tonne" | "per_km" | "monthly_contract";

export interface QuoteInput {
  method: BillingMethod;
  /** Per trip, per tonne, per km, or the monthly fee, in cents. */
  rate_cents: number;
  /** One way, loaded, in km. */
  distance_km: number;
  /** Total cargo across all trips. */
  weight_tonnes: number;
  trips: number;
  /** The lorry comes back empty over the same distance. */
  return_empty: boolean;
  kmpl_loaded: number;
  kmpl_empty: number;
  fuel_price_cents: number;
  /** Per trip. */
  tolls_cents: number;
  crew_cents: number;
  other_cents: number;
}

export interface QuoteResult {
  price_cents: number;
  loaded_km: number;
  empty_km: number;
  fuel_litres: number;
  fuel_cents: number;
  cost_per_trip_cents: number;
  total_cost_cents: number;
  profit_cents: number;
  /** Profit as a percentage of the price, to one decimal place; null when there is no price. */
  margin_pct: number | null;
}

/** Round half up. (Math.round and Python's round() disagree on negatives and halves, so both sides use this.) */
const half = (x: number) => Math.floor(x + 0.5);

export function priceFor(input: QuoteInput): number {
  switch (input.method) {
    case "per_trip":
      return input.rate_cents * input.trips;
    case "per_tonne":
      return half(input.rate_cents * input.weight_tonnes);
    case "per_km":
      return half(input.rate_cents * input.distance_km * input.trips);
    case "monthly_contract":
      return input.rate_cents;
  }
}

export function quote(input: QuoteInput): QuoteResult {
  const loaded_km = input.distance_km;
  const empty_km = input.return_empty ? input.distance_km : 0;
  const litres = loaded_km / input.kmpl_loaded + empty_km / input.kmpl_empty;
  const fuel_cents = half(litres * input.fuel_price_cents);
  const cost_per_trip_cents = fuel_cents + input.tolls_cents + input.crew_cents + input.other_cents;
  const total_cost_cents = cost_per_trip_cents * input.trips;
  const price_cents = priceFor(input);
  const profit_cents = price_cents - total_cost_cents;
  return {
    price_cents,
    loaded_km,
    empty_km,
    fuel_litres: half(litres * 100) / 100,
    fuel_cents,
    cost_per_trip_cents,
    total_cost_cents,
    profit_cents,
    margin_pct: price_cents > 0 ? half((profit_cents / price_cents) * 1000) / 10 : null,
  };
}
