import type { ActionType } from "./types";

export interface Explanation {
  /** What the office said, in words the driver can follow. */
  why: string;
  /** What to do about it. */
  hint: string;
}

const TRIP_STEP: Partial<Record<ActionType, string>> = {
  "trip.start": "start",
  "trip.loading": "loading",
  "trip.deliver": "delivery",
  "trip.end": "end",
};

const STATE_WORDS: Record<string, string> = {
  scheduled: "not started yet",
  in_progress: "on the road",
  delivered: "delivered",
  completed: "ended",
  cancelled: "cancelled",
};

/**
 * Turns a refused record into a reason and a next step. `tripStatus` is what the office shows for the trip right now, when the phone could
 * find out (it can only ask while it has a network), otherwise null.
 */
export function explainRejection(
  item: { type: ActionType; code?: string; message?: string },
  tripStatus: string | null,
): Explanation {
  const step = TRIP_STEP[item.type];
  if (item.code === "wrong_status" && step) {
    if (tripStatus === "delivered" || tripStatus === "completed") {
      return {
        why: `The office already has this trip as ${STATE_WORDS[tripStatus]}.`,
        hint: "Nothing more needs sending for this step. Delete it.",
      };
    }
    if (tripStatus === "scheduled") {
      return {
        why: "The office never received the start of this trip, so it cannot take the next steps.",
        hint: "Delete this, then start the trip again. Ask the office if the start is refused.",
      };
    }
    if (tripStatus === "cancelled") {
      return { why: "The office cancelled this trip.", hint: "Delete this." };
    }
    return {
      why: "The office's record of this trip is not at the right step for this.",
      hint: "Look at the trip. If it already shows delivered or ended, delete this. If it never started, start it again.",
    };
  }
  if (item.code === "documents_expired") {
    return {
      why: item.message ?? "A licence or insurance has run out.",
      hint: "Send the renewal from the trip, or ask the owner to allow this trip. Then try again.",
    };
  }
  if (item.code === "inspection_required") {
    return {
      why: "Today's pre-trip inspection is missing.",
      hint: "Do the inspection, then try again.",
    };
  }
  if (item.code === "already_on_trip") {
    return {
      why: "This lorry or driver is already on another trip.",
      hint: "End the other trip first, then try again.",
    };
  }
  return {
    why: item.message ?? "The office could not accept this.",
    hint: "Try again. If it keeps failing, delete it and tell the office.",
  };
}

/** The trip a queued action is about, when it is about one. */
export const tripIdOf = (payload: Record<string, unknown>): string | null =>
  typeof payload.trip_id === "string" ? payload.trip_id : null;
