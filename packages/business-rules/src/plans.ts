/**
 * Plans and pricing (masterplan Section 9): the price of a fleet, what each plan includes, and whether an account has full access, a
 * grace period or is read-only. Mirrored by apps/api/app/plan_rules.py and tested against plan-cases.json on both sides. Money is whole
 * cents. The prices are the masterplan's proposed starting points, to be validated with real fleet owners.
 */

export type Plan = "starter" | "standard" | "premium";
export const PLANS: Plan[] = ["starter", "standard", "premium"];
const RANK: Record<Plan, number> = { starter: 0, standard: 1, premium: 2 };
export const PLAN_PRICE_CENTS: Record<Plan, number> = {
  starter: 100_000,
  standard: 180_000,
  premium: 280_000,
};
export const PAYROLL_CENTS = 10_000;
export const TRIAL_DAYS = 14;
export const GRACE_DAYS = 7;
export const SMS_BUNDLES: Record<number, number> = { 500: 60_000, 2000: 240_000, 5000: 600_000 };
const ANNUAL_MONTHS_PAID = 10;
const VOLUME_FROM = 11;
const VOLUME_TO = 30;
const VOLUME_PCT = 10;
const CUSTOM_FROM = 31;
const DAY = 86_400_000;

export const FEATURES: Record<string, Plan> = {
  trackers: "standard",
  live_map: "standard",
  replay: "standard",
  geofences: "standard",
  scorecards: "standard",
  tyres_parts: "standard",
  tracking_links: "standard",
  etims: "standard",
  custom_reports: "standard",
  all_roles: "standard",
  fuel_sensors: "premium",
  immobiliser: "premium",
  predictions: "premium",
  ask: "premium",
  scheduled_reports: "premium",
};

const halfUp = (n: number, d: number) => Math.floor((2 * n + d) / (2 * d));

/** Whether a plan includes a feature. Anything not listed is in every plan. */
export function planAllows(plan: Plan, feature: string): boolean {
  const needed = FEATURES[feature];
  return needed === undefined || RANK[plan] >= RANK[needed];
}

/** The highest plan among a fleet's vehicles. A fleet with no vehicles yet has what a trial gives: Standard. */
export function bestPlan(plans: Plan[]): Plan {
  return plans.length ? plans.reduce((a, b) => (RANK[b] > RANK[a] ? b : a)) : "standard";
}

export interface SubscriptionQuote {
  vehicles: number;
  lines: { plan: Plan; vehicles: number; unit_cents: number; cents: number }[];
  list_cents: number;
  discount_pct: number;
  discount_cents: number;
  vehicles_cents: number;
  payroll_cents: number;
  monthly_cents: number;
  period: "monthly" | "annual";
  months_paid: number;
  months_covered: number;
  total_cents: number;
  saving_cents: number;
  custom: boolean;
}

/** What a fleet pays. 11 to 30 vehicles get 10 percent off the vehicle charges; 31 and more are priced by agreement. */
export function quoteSubscription(
  plans: Plan[],
  options: { period?: "monthly" | "annual"; payroll_employees?: number } = {},
): SubscriptionQuote {
  const period = options.period ?? "monthly";
  const lines = PLANS.map((p) => {
    const vehicles = plans.filter((x) => x === p).length;
    return {
      plan: p,
      vehicles,
      unit_cents: PLAN_PRICE_CENTS[p],
      cents: vehicles * PLAN_PRICE_CENTS[p],
    };
  }).filter((l) => l.vehicles > 0);
  const listCents = lines.reduce((a, l) => a + l.cents, 0);
  const n = plans.length;
  const discountPct = n >= VOLUME_FROM && n <= VOLUME_TO ? VOLUME_PCT : 0;
  const discountCents = halfUp(listCents * discountPct, 100);
  const vehiclesCents = listCents - discountCents;
  const payrollCents = Math.max(0, options.payroll_employees ?? 0) * PAYROLL_CENTS;
  const monthlyCents = vehiclesCents + payrollCents;
  const [monthsPaid, monthsCovered] = period === "annual" ? [ANNUAL_MONTHS_PAID, 12] : [1, 1];
  const total = monthlyCents * monthsPaid;
  return {
    vehicles: n,
    lines,
    list_cents: listCents,
    discount_pct: discountPct,
    discount_cents: discountCents,
    vehicles_cents: vehiclesCents,
    payroll_cents: payrollCents,
    monthly_cents: monthlyCents,
    period,
    months_paid: monthsPaid,
    months_covered: monthsCovered,
    total_cents: total,
    saving_cents: monthlyCents * monthsCovered - total,
    custom: n >= CUSTOM_FROM,
  };
}

export type AccessStateName = "complimentary" | "trialing" | "active" | "grace" | "read_only";

const daysUp = (ms: number) => Math.max(0, Math.ceil(Math.floor(ms / 1000) / 86_400));

/**
 * Full access while on trial or paid up; full access with a warning for 7 days after either ends; read-only after that. Read-only
 * never deletes anything, and paying brings full access straight back. Times are ISO strings.
 */
export function accessState(input: {
  complimentary: boolean;
  trial_ends_at: string;
  paid_until: string | null;
  now: string;
  cancelled?: boolean;
}): {
  state: AccessStateName;
  ends_at: string | null;
  grace_ends_at: string | null;
  days_left: number | null;
  writable: boolean;
} {
  const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
  if (input.complimentary)
    return {
      state: "complimentary",
      ends_at: null,
      grace_ends_at: null,
      days_left: null,
      writable: true,
    };
  const now = Date.parse(input.now);
  const ends = Date.parse(input.paid_until ?? input.trial_ends_at);
  const grace = ends + GRACE_DAYS * DAY;
  if (input.cancelled)
    return {
      state: "read_only",
      ends_at: iso(ends),
      grace_ends_at: null,
      days_left: 0,
      writable: false,
    };
  if (now <= ends)
    return {
      state: input.paid_until ? "active" : "trialing",
      ends_at: iso(ends),
      grace_ends_at: iso(grace),
      days_left: daysUp(ends - now),
      writable: true,
    };
  if (now <= grace)
    return {
      state: "grace",
      ends_at: iso(ends),
      grace_ends_at: iso(grace),
      days_left: daysUp(grace - now),
      writable: true,
    };
  return {
    state: "read_only",
    ends_at: iso(ends),
    grace_ends_at: iso(grace),
    days_left: 0,
    writable: false,
  };
}
