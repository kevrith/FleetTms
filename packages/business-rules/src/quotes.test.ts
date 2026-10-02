import { describe, expect, it } from "vitest";
import cases from "./quote-cases.json";
import { quote, type QuoteInput } from "./quotes";

describe("quote", () => {
  for (const c of cases) {
    it(c.name, () => {
      expect(quote(c.input as QuoteInput)).toEqual(c.expected);
    });
  }
});
