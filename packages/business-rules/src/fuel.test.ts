import { describe, expect, it } from "vitest";
import { litresFromTotal } from "./fuel";

describe("litresFromTotal", () => {
  it("divides the total paid by the price per litre", () => {
    expect(litresFromTotal(18500, 185)).toBe("100");
    expect(litresFromTotal(9500, 190)).toBe("50");
  });
  it("rounds to two decimal places", () => {
    expect(litresFromTotal(1000, 185)).toBe("5.41");
  });
  it("stays empty until both numbers are usable", () => {
    expect(litresFromTotal(0, 185)).toBe("");
    expect(litresFromTotal(18500, 0)).toBe("");
    expect(litresFromTotal(Number.NaN, 185)).toBe("");
  });
});
