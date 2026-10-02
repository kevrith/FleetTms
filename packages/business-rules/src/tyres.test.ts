import { describe, expect, it } from "vitest";
import { positionLabel } from "./tyres";

describe("positionLabel", () => {
  it("turns a position code into words", () => {
    expect(positionLabel("steer_left")).toBe("Steer left");
    expect(positionLabel("drive1_right_inner")).toBe("Drive1 right inner");
    expect(positionLabel("spare")).toBe("Spare");
  });
  it("is empty for no position", () => {
    expect(positionLabel(null)).toBe("");
    expect(positionLabel(undefined)).toBe("");
  });
});
