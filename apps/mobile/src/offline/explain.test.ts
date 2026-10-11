import { describe, expect, it } from "vitest";
import { explainRejection, tripIdOf } from "./explain";

describe("explainRejection", () => {
  const deliver = {
    type: "trip.deliver" as const,
    code: "wrong_status",
    message: "Only a trip in progress can be delivered.",
  };

  it("says there is nothing left to send when the office already has the trip delivered or ended", () => {
    expect(explainRejection(deliver, "delivered").why).toContain(
      "already has this trip as delivered",
    );
    expect(explainRejection(deliver, "completed").why).toContain("as ended");
    expect(explainRejection(deliver, "delivered").hint).toContain("Delete");
  });
  it("says the start never arrived when the office shows the trip as not started", () => {
    const e = explainRejection(deliver, "scheduled");
    expect(e.why).toContain("never received the start");
    expect(e.hint).toContain("start the trip again");
  });
  it("still helps when the phone could not find out the trip's state", () => {
    const e = explainRejection(deliver, null);
    expect(e.why).toContain("not at the right step");
    expect(e.why).not.toContain("Only a trip in progress");
  });
  it("explains the other refusals a driver can act on", () => {
    expect(
      explainRejection(
        {
          type: "trip.start",
          code: "documents_expired",
          message: "Insurance for KCA 123A expired on 2026-10-01.",
        },
        null,
      ).why,
    ).toContain("Insurance for KCA 123A expired");
    expect(
      explainRejection({ type: "trip.start", code: "inspection_required" }, null).hint,
    ).toContain("inspection");
    expect(explainRejection({ type: "trip.start", code: "already_on_trip" }, null).why).toContain(
      "another trip",
    );
  });
  it("falls back to the office's own words", () => {
    expect(
      explainRejection(
        { type: "fuel.add", code: "x", message: "That receipt was already used." },
        null,
      ).why,
    ).toBe("That receipt was already used.");
    expect(explainRejection({ type: "fuel.add" }, null).why).toBe(
      "The office could not accept this.",
    );
  });
});

describe("tripIdOf", () => {
  it("reads the trip an action is about", () => {
    expect(tripIdOf({ trip_id: "t1" })).toBe("t1");
    expect(tripIdOf({})).toBeNull();
  });
});
