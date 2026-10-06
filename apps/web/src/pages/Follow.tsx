import type { DeliveryFollow } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { MapView } from "../MapView";
import PublicShell from "./PublicShell";

/** The page a client opens from the link they were sent. No sign-in, nothing but this delivery. */
export default function Follow() {
  const { token = "" } = useParams();
  const [d, setD] = useState<DeliveryFollow | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setD(await api.followDelivery(token));
      setGone(null);
    } catch (e) {
      const status = (e as { status?: number }).status;
      setD(null);
      setGone(
        status === 404
          ? "This link is not valid."
          : e instanceof Error
            ? e.message
            : "This link no longer works.",
      );
    }
  }, [token]);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);
  const arrival = d?.expected_arrival ? new Date(d.expected_arrival) : null;
  return (
    <PublicShell>
      {gone && (
        <section className="card">
          <h2>Delivery tracking</h2>
          <p>{gone}</p>
        </section>
      )}
      {d && (
        <>
          <h2>{d.business}</h2>
          <p>
            {[d.origin, d.destination].filter(Boolean).join(" to ")}
            {d.cargo ? `, ${d.cargo}` : ""}
          </p>
          {d.status === "scheduled" && (
            <p className="banner">
              Your delivery has not left yet. This page updates by itself once it is on the road.
            </p>
          )}
          {d.status === "on_the_way" && (
            <>
              <p className="status ok">On the way</p>
              {d.progress_pct !== null && (
                <div
                  style={{ background: "#e5e7eb", borderRadius: 8, height: 14, overflow: "hidden" }}
                  role="progressbar"
                  aria-valuenow={d.progress_pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    style={{ width: `${d.progress_pct}%`, background: "#16a34a", height: "100%" }}
                  />
                </div>
              )}
              <p>
                {arrival
                  ? `Expected about ${arrival.toLocaleTimeString("en-KE", { hour: "2-digit", minute: "2-digit" })}${d.minutes_remaining !== null ? ` (${d.minutes_remaining} minutes to go)` : ""}.`
                  : "We will show an expected arrival once the lorry reports its position."}
              </p>
              {d.position && (
                <>
                  <MapView
                    markers={[
                      {
                        id: "lorry",
                        lat: d.position.lat,
                        lng: d.position.lng,
                        colour: d.position.stale ? "#d97706" : "#16a34a",
                        label: "Your delivery",
                        big: true,
                      },
                    ]}
                    height={320}
                  />
                  <p className="muted">
                    Position updated{" "}
                    {new Date(d.position.updated_at).toLocaleTimeString("en-KE", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                    {d.position.stale
                      ? ". The lorry has not reported for a while; this is where it was last seen."
                      : "."}
                  </p>
                </>
              )}
            </>
          )}
        </>
      )}
    </PublicShell>
  );
}
