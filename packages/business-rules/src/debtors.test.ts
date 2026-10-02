import { describe, expect, it } from "vitest";
import { ageingBucket, invoiceNumberFrom, reminderOffsetDue } from "./debtors";
import cases from "./debtor-cases.json";

describe("ageingBucket", () => {
  for (const c of cases.ageing) {
    it(c.name, () => {
      expect(ageingBucket(c.due, c.today)).toBe(c.expected);
    });
  }
});

describe("invoiceNumberFrom", () => {
  for (const c of cases.references) {
    it(c.name, () => {
      expect(invoiceNumberFrom(c.text)).toBe(c.expected);
    });
  }
});

describe("reminderOffsetDue", () => {
  for (const c of cases.reminders) {
    it(c.name, () => {
      expect(
        reminderOffsetDue({ due: c.due, today: c.today, offsets: c.offsets, sent: c.sent }),
      ).toBe(c.expected);
    });
  }
});
