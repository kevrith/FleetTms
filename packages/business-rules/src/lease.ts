/**
 * Leasing, asset finance, ownership costs and net profit (masterplan 5.23 and 5.15). Mirrored by
 * apps/api/app/lease_rules.py and tested against lease-cases.json, finance-cases.json and profit-cases.json on both
 * sides. Money is whole cents; percentages are handled in hundredths so no floating point touches the money.
 */

export const divHalf = (n: number, d: number) => Math.floor((2 * n + d) / (2 * d));
const hundredths = (pct: number) => Math.round(pct * 100);
/** pct percent of an amount, rounded half up. Nothing is shared out of a loss. */
export const share = (amount: number, pct: number) =>
  divHalf(Math.max(0, amount) * hundredths(pct), 10_000);

const parse = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  return { y, m, d };
};
const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const iso = (y: number, m: number, d: number) =>
  `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
const dayCount = (isoDate: string) => Date.parse(`${isoDate}T00:00:00Z`) / 86_400_000;

/** The same day of a later month, or its last day if that month is shorter. */
export function addMonths(isoDate: string, months: number): string {
  const { y, m, d } = parse(isoDate);
  const index = y * 12 + m - 1 + months;
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  return iso(year, month, Math.min(d, daysIn(year, month)));
}

export interface LeaseTerms {
  start: string;
  end?: string | null;
  fixed_cents?: number;
  fixed_period?: "month" | "week" | "day" | null;
  per_trip_cents?: number;
  per_km_cents?: number;
  revenue_pct?: number;
  profit_pct?: number;
  /** Per month. */
  min_guarantee_cents?: number;
}

export interface LeaseUsage {
  trips?: number;
  km?: number;
  revenue_cents?: number;
  /** Gross profit before the lease, for a share of profit. */
  profit_cents?: number;
}

export interface LeaseCharge {
  days_active: number;
  days_in_month: number;
  fixed_cents: number;
  trips_cents: number;
  km_cents: number;
  revenue_share_cents: number;
  profit_share_cents: number;
  subtotal_cents: number;
  guarantee_cents: number;
  guarantee_applied: boolean;
  charge_cents: number;
}

/** What the lease charges for the calendar month containing `month` (any ISO date in it). */
export function monthCharge(terms: LeaseTerms, month: string, usage: LeaseUsage): LeaseCharge {
  const { y, m } = parse(month);
  const inMonth = daysIn(y, m);
  const first = iso(y, m, 1);
  const last = iso(y, m, inMonth);
  const start = terms.start > first ? terms.start : first;
  const end = terms.end && terms.end < last ? terms.end : last;
  const days = Math.max(0, dayCount(end) - dayCount(start) + 1);
  if (days === 0) {
    return {
      days_active: 0,
      days_in_month: inMonth,
      fixed_cents: 0,
      trips_cents: 0,
      km_cents: 0,
      revenue_share_cents: 0,
      profit_share_cents: 0,
      subtotal_cents: 0,
      guarantee_cents: 0,
      guarantee_applied: false,
      charge_cents: 0,
    };
  }
  const f = terms.fixed_cents ?? 0;
  const fixed =
    terms.fixed_period === "month"
      ? divHalf(f * days, inMonth)
      : terms.fixed_period === "week"
        ? divHalf(f * days, 7)
        : terms.fixed_period === "day"
          ? f * days
          : 0;
  const trips = (terms.per_trip_cents ?? 0) * Math.max(0, usage.trips ?? 0);
  const km = (terms.per_km_cents ?? 0) * Math.max(0, usage.km ?? 0);
  const revenue_share = share(usage.revenue_cents ?? 0, terms.revenue_pct ?? 0);
  const profit_share = share(usage.profit_cents ?? 0, terms.profit_pct ?? 0);
  const subtotal = fixed + trips + km + revenue_share + profit_share;
  const g = terms.min_guarantee_cents ?? 0;
  const guarantee = g ? divHalf(g * days, inMonth) : 0;
  return {
    days_active: days,
    days_in_month: inMonth,
    fixed_cents: fixed,
    trips_cents: trips,
    km_cents: km,
    revenue_share_cents: revenue_share,
    profit_share_cents: profit_share,
    subtotal_cents: subtotal,
    guarantee_cents: guarantee,
    guarantee_applied: guarantee > subtotal,
    charge_cents: Math.max(subtotal, guarantee),
  };
}

export interface LeaseEntry {
  kind: "charge" | "offset" | "payment" | "adjustment";
  amount_cents: number;
  due_date: string | null;
}

/** Where a lease account stands: the balance, what is past due after payments and offsets, and the next due date. */
export function leaseStanding(entries: LeaseEntry[], today: string) {
  const balance = entries.reduce((a, e) => a + e.amount_cents, 0);
  const dueNow = entries
    .filter(
      (e) =>
        (e.kind === "charge" || e.kind === "adjustment") &&
        e.due_date !== null &&
        e.due_date < today,
    )
    .reduce((a, e) => a + e.amount_cents, 0);
  const credits = -entries
    .filter((e) => e.kind === "offset" || e.kind === "payment")
    .reduce((a, e) => a + e.amount_cents, 0);
  const upcoming = entries
    .filter((e) => e.kind === "charge" && e.due_date !== null && e.due_date >= today)
    .map((e) => e.due_date as string)
    .sort();
  return {
    balance_cents: balance,
    overdue_cents: Math.max(0, Math.min(balance, dueNow - credits)),
    next_due_date: upcoming[0] !== undefined && balance > 0 ? upcoming[0] : null,
  };
}

// ---- asset finance ----

/** The level monthly repayment on a reducing balance. */
export function instalmentCents(principal: number, annualRatePct: number, months: number): number {
  if (months <= 0) throw new Error("A loan needs at least one month.");
  const rate = annualRatePct / 1200;
  if (rate === 0) return divHalf(principal, months);
  return Math.round((principal * rate) / (1 - (1 + rate) ** -months));
}

export interface FinanceRow {
  number: number;
  due_date: string;
  amount_cents: number;
  interest_cents: number;
  principal_cents: number;
  balance_cents: number;
}

/** Every repayment, the interest in it and the balance after. The last one clears whatever is left. */
export function financeSchedule(
  principal: number,
  annualRatePct: number,
  months: number,
  firstDue: string,
  instalment?: number | null,
): FinanceRow[] {
  const payment = instalment ?? instalmentCents(principal, annualRatePct, months);
  const rateH = hundredths(annualRatePct);
  let balance = principal;
  const rows: FinanceRow[] = [];
  for (let n = 1; n <= months; n++) {
    const interest = divHalf(balance * rateH, 12 * 10_000);
    let amount: number;
    let part: number;
    if (n === months || payment >= balance + interest) {
      amount = balance + interest;
      part = balance;
    } else {
      amount = payment;
      part = Math.max(0, amount - interest);
    }
    balance -= part;
    rows.push({
      number: n,
      due_date: addMonths(firstDue, n - 1),
      amount_cents: amount,
      interest_cents: interest,
      principal_cents: part,
      balance_cents: balance,
    });
    if (balance === 0) break;
  }
  return rows;
}

// ---- ownership costs ----

export interface OwnershipItem {
  kind: "insurance" | "licence" | "depreciation" | "other";
  amount_cents: number;
  period: "year" | "month";
  salvage_cents: number;
  life_months: number | null;
  start: string;
  end: string | null;
}

/** What a fixed ownership cost comes to for the calendar month containing `month`. */
export function ownershipMonthly(item: OwnershipItem, month: string): number {
  const { y, m } = parse(month);
  const inMonth = daysIn(y, m);
  const first = iso(y, m, 1);
  const last = iso(y, m, inMonth);
  const runStart = item.start > first ? item.start : first;
  let runEnd = item.end && item.end < last ? item.end : last;
  let base: number;
  if (item.kind === "depreciation") {
    if (!item.life_months || item.life_months <= 0) return 0;
    const lifeEnd = dayCount(addMonths(item.start, item.life_months)) - 1;
    if (dayCount(runEnd) > lifeEnd)
      runEnd = new Date(lifeEnd * 86_400_000).toISOString().slice(0, 10);
    base = divHalf(Math.max(0, item.amount_cents - item.salvage_cents), item.life_months);
  } else {
    base = item.period === "year" ? divHalf(item.amount_cents, 12) : item.amount_cents;
  }
  const days = dayCount(runEnd) - dayCount(runStart) + 1;
  if (item.start > last || (item.end && item.end < first) || days <= 0) return 0;
  return days === inMonth ? base : divHalf(base * days, inMonth);
}

// ---- profit ----

export interface NetProfitInput {
  revenue_cents: number;
  operating_cents: number;
  lease_charges_cents?: number;
  offsets_cents?: number;
  finance_cents?: number;
  ownership_cents?: number;
}

/** Gross profit, what is payable to the lorry's owner (charges less offsets), and the net after finance and ownership costs. */
export function netProfit(i: NetProfitInput) {
  const gross = i.revenue_cents - i.operating_cents;
  const payable = (i.lease_charges_cents ?? 0) - (i.offsets_cents ?? 0);
  return {
    gross_profit_cents: gross,
    lease_payable_cents: payable,
    net_profit_cents: gross - payable - (i.finance_cents ?? 0) - (i.ownership_cents ?? 0),
  };
}

/** True when, for the last `run` months in a row, the lorry's owner earned more than the operator. Oldest first. */
export function leaseNotPaying(
  months: { lessor_cents: number; operator_net_cents: number }[],
  run = 3,
): boolean {
  const recent = months.slice(-run);
  return recent.length === run && recent.every((m) => m.lessor_cents > m.operator_net_cents);
}
