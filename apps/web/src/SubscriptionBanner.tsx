import type { AccessInfo } from "@fleettms/types";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";

/** A warning for everyone when the free trial is nearly over, a payment is overdue, or the account is read-only. */
export function SubscriptionBanner() {
  const { can, me } = useAuth();
  const [access, setAccess] = useState<AccessInfo | null>(null);
  useEffect(() => {
    if (!me?.business || (!can("trips.own") && !can("vehicles.view") && !can("business.manage")))
      return;
    const load = () =>
      api
        .subscriptionBanner()
        .then(setAccess)
        .catch(() => setAccess(null));
    void load();
    const timer = setInterval(load, 300_000);
    return () => clearInterval(timer);
  }, [me?.business, can]);
  if (!access) return null;
  const owner = can("business.manage");
  const link = owner ? (
    <Link to="/settings/subscription">Open the subscription</Link>
  ) : (
    <span>Ask the owner to pay.</span>
  );
  if (access.state === "suspended")
    return (
      <p className="banner bad" role="alert">
        <AlertTriangle size={18} /> This account is on hold, so it is read-only. Contact FleetTms
        support.
      </p>
    );
  if (access.state === "read_only")
    return (
      <p className="banner bad" role="alert">
        <AlertTriangle size={18} /> The subscription has not been paid, so this account is
        read-only. Nothing has been lost. {link}
      </p>
    );
  if (access.state === "grace")
    return (
      <p className="banner warn" role="status">
        <AlertTriangle size={18} /> The subscription is overdue. Everything works for{" "}
        {access.days_left} more day(s), then the account becomes read-only. {link}
      </p>
    );
  if (
    (access.state === "trialing" || access.state === "active") &&
    access.days_left !== null &&
    access.days_left <= 3
  )
    return (
      <p className="banner warn" role="status">
        <AlertTriangle size={18} />{" "}
        {access.state === "trialing" ? "The free trial" : "The subscription"} ends in{" "}
        {access.days_left} day(s). {link}
      </p>
    );
  return null;
}
