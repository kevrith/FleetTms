import { describe, expect, it } from "vitest";
import { daysPhrase, parseDateInput } from "./dates";

describe("parseDateInput", () => {
  it("reads the ways people write a date in Kenya", () => {
    expect(parseDateInput("31/12/2026")).toBe("2026-12-31");
    expect(parseDateInput("1-3-2027")).toBe("2027-03-01");
    expect(parseDateInput("05.06.26")).toBe("2026-06-05");
    expect(parseDateInput(" 2026-12-31 ")).toBe("2026-12-31");
  });
  it("refuses what is not a real date", () => {
    expect(parseDateInput("31/02/2026")).toBeNull();
    expect(parseDateInput("13/13/2026")).toBeNull();
    expect(parseDateInput("tomorrow")).toBeNull();
    expect(parseDateInput("")).toBeNull();
    expect(parseDateInput("2026/12/31")).toBeNull();
  });
  it("knows a leap day", () => {
    expect(parseDateInput("29/02/2028")).toBe("2028-02-29");
    expect(parseDateInput("29/02/2027")).toBeNull();
  });
});

describe("daysPhrase", () => {
  it("says it plainly", () => {
    expect(daysPhrase(23)).toBe("In 23 days");
    expect(daysPhrase(1)).toBe("In 1 day");
    expect(daysPhrase(0)).toBe("Expires today");
    expect(daysPhrase(-3)).toBe("Expired 3 days ago");
  });
});
