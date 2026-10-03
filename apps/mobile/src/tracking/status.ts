import { useEffect, useState } from "react";
import { tracker } from "./task";

export type TrackingProblem = "denied" | "background_denied" | "failed" | null;

let problem: TrackingProblem = null;
export const setTrackingProblem = (p: TrackingProblem) => {
  problem = p;
};

export interface TrackingStatus {
  /** A trip is being tracked right now. */
  on: boolean;
  /** Fixes recorded and not yet sent. */
  waiting: number;
  /** Why tracking could not start, if it could not. */
  problem: TrackingProblem;
}

/** What the driver is shown about tracking: on or off, how much is waiting to be sent, and any permission problem. */
export function useTrackingStatus(): TrackingStatus {
  const read = (): TrackingStatus => ({
    on: tracker.isTracking(),
    waiting: tracker.waiting(),
    problem,
  });
  const [status, setStatus] = useState<TrackingStatus>(read);
  useEffect(() => {
    const timer = setInterval(() => setStatus(read), 3000);
    return () => clearInterval(timer);
  }, []);
  return status;
}
