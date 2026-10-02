import { describe, expect, it } from "vitest";
import { availableViews, defaultView, isOtpOnly } from "./roles";

describe("roles", () => {
  it("lets an owner-driver switch between views", () => {
    expect(availableViews(["owner", "driver"])).toEqual(["owner", "driver"]);
    expect(defaultView(["owner", "driver"])).toBe("owner");
  });
  it("gives drivers and turnboys the driver view only", () => {
    expect(availableViews(["driver"])).toEqual(["driver"]);
    expect(availableViews(["turnboy"])).toEqual(["driver"]);
  });
  it("gives business roles the owner view only", () => {
    expect(availableViews(["manager"])).toEqual(["owner"]);
    expect(availableViews(["accountant", "workshop"])).toEqual(["owner"]);
  });
  it("only drivers and turnboys use phone codes", () => {
    expect(isOtpOnly(["driver", "turnboy"])).toBe(true);
    expect(isOtpOnly(["owner", "driver"])).toBe(false);
    expect(isOtpOnly([])).toBe(false);
  });
});
