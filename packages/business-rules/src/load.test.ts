import { describe, expect, it } from "vitest";
import cases from "./load-cases.json";
import { overloadKg, type LoadInput } from "./load";

describe("overloadKg", () => {
  for (const c of cases) {
    it(c.name, () => {
      expect(overloadKg(c.input as LoadInput)).toBe(c.expected);
    });
  }
});
