import { describe, expect, it } from "vitest";
import {
  accessState,
  bestPlan,
  planAllows,
  quoteSubscription,
  type AccessStateName,
  type Plan,
} from "./plans";
import cases from "./plan-cases.json";

describe("subscription prices", () => {
  for (const c of cases.quotes) {
    it(c.name, () => {
      expect(
        quoteSubscription(c.plans as Plan[], {
          period: c.period as "monthly" | "annual",
          payroll_employees: c.payroll_employees,
        }),
      ).toEqual(c.expected);
    });
  }
});

describe("what a plan includes", () => {
  it("features by plan", () => {
    for (const c of cases.allows)
      expect(planAllows(c.plan as Plan, c.feature), `${c.plan} ${c.feature}`).toBe(c.expected);
  });
  it("the best plan of a fleet", () => {
    for (const c of cases.best) expect(bestPlan(c.plans as Plan[])).toBe(c.expected);
  });
});

describe("access state", () => {
  for (const c of cases.access) {
    it(c.name, () => {
      const got = accessState({ ...c.input, now: c.now });
      expect(got).toEqual({
        state: c.expected.state as AccessStateName,
        days_left: c.expected.days_left,
        writable: c.expected.writable,
        ends_at: c.expected.ends_at,
        grace_ends_at: c.expected.grace_ends_at,
      });
    });
  }
});
