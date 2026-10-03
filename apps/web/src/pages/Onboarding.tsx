import type { Onboarding } from "@fleettms/types";
import { CheckCircle2, Circle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, errorMessage } from "../ui";

/** The owner's getting-started checklist. It ticks itself off from what is already set up, and can be hidden. */
export function OnboardingCard() {
  const { can } = useAuth();
  const [data, setData] = useState<Onboarding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("business.manage");
  const load = useCallback(() => {
    if (allowed)
      api
        .onboarding()
        .then(setData)
        .catch(() => setData(null));
  }, [allowed]);
  useEffect(load, [load]);
  if (!allowed || !data || data.dismissed) return null;
  async function hide() {
    try {
      await api.dismissOnboarding();
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const finished = data.done === data.total;
  return (
    <Card title={`Getting started: ${data.done} of ${data.total} done`}>
      {error && <p className="banner bad">{error}</p>}
      <progress value={data.done} max={data.total} aria-label="Getting started progress" />
      <ul className="list">
        {data.items.map((i) => (
          <li key={i.key}>
            <span>
              {i.done ? (
                <CheckCircle2 size={16} aria-label="Done" />
              ) : (
                <Circle size={16} aria-label="Not done yet" />
              )}{" "}
              {i.done ? (
                i.title
              ) : (
                <Link to={i.link}>
                  <strong>{i.title}</strong>
                </Link>
              )}
            </span>
            <span className="muted">{i.detail}</span>
          </li>
        ))}
      </ul>
      <button className="btn" type="button" onClick={hide}>
        {finished ? "All done: hide this" : "Hide this"}
      </button>
    </Card>
  );
}
