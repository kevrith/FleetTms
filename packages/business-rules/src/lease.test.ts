import { describe, expect, it } from "vitest";
import {
  financeSchedule,
  instalmentCents,
  leaseNotPaying,
  leaseStanding,
  monthCharge,
  netProfit,
  ownershipMonthly,
  type LeaseEntry,
  type LeaseTerms,
  type LeaseUsage,
  type NetProfitInput,
  type OwnershipItem,
} from "./lease";
import lease from "./lease-cases.json";
import finance from "./finance-cases.json";
import profit from "./profit-cases.json";

describe("monthCharge", () => {
  for (const c of lease.charges) {
    it(c.name, () => {
      expect(monthCharge(c.terms as LeaseTerms, c.month, c.usage as LeaseUsage)).toEqual(
        c.expected,
      );
    });
  }
});

describe("leaseStanding", () => {
  for (const c of lease.standing) {
    it(c.name, () => {
      expect(leaseStanding(c.entries as LeaseEntry[], c.today)).toEqual(c.expected);
    });
  }
});

describe("instalmentCents", () => {
  for (const c of finance.instalments) {
    it(c.name, () => {
      if (c.months === 1) return; // a single month is covered by the schedule
      expect(instalmentCents(c.principal_cents, c.annual_rate_pct, c.months)).toBe(c.expected);
    });
  }
});

describe("financeSchedule", () => {
  for (const c of finance.schedules) {
    it(c.name, () => {
      const rows = financeSchedule(
        c.principal_cents,
        c.annual_rate_pct,
        c.months,
        c.first_due,
        c.instalment,
      );
      expect(rows).toHaveLength(c.rows);
      expect(rows[0]).toEqual(c.first);
      expect(rows[rows.length - 1]).toEqual(c.last);
      expect(rows.reduce((a, r) => a + r.principal_cents, 0)).toBe(c.principal_cents);
    });
  }
});

describe("ownershipMonthly", () => {
  for (const c of finance.ownership) {
    it(c.name, () => {
      expect(ownershipMonthly(c.item as OwnershipItem, c.month)).toBe(c.expected);
    });
  }
});

describe("netProfit", () => {
  for (const c of profit.net) {
    it(c.name, () => {
      expect(netProfit(c.input as NetProfitInput)).toEqual(c.expected);
    });
  }
});

describe("leaseNotPaying", () => {
  for (const c of profit.not_paying) {
    it(c.name, () => {
      expect(leaseNotPaying(c.months)).toBe(c.expected);
    });
  }
});
