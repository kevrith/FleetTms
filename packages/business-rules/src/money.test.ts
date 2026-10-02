import { describe, expect, it } from "vitest";
import { centsToKes, formatKes, kesToCents } from "./money";

describe("money", () => {
  it("converts KES to cents without float drift", () => {
    expect(kesToCents(19.99)).toBe(1999);
    expect(centsToKes(1999)).toBe(19.99);
  });
  it("formats", () => {
    expect(formatKes(16000000)).toBe("KES 160,000.00");
  });
});
