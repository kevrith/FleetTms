import type { AccessStateName } from "@fleettms/types";

export { kes, nairobiTime } from "../labels";

/** 1,800,000 cents as "18K", 250,000,000 as "2.5M": for chart axes and tight spaces (always KES). */
export function shortKes(cents: number): string {
  const v = cents / 100;
  if (Math.abs(v) >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${+(v / 1_000).toFixed(1)}K`;
  return String(Math.round(v));
}

export const date = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString("en-GB", {
        timeZone: "Africa/Nairobi",
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "never";

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        timeZone: "Africa/Nairobi",
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "never";

/** "in 5 days", "today", "3 days ago". */
export function daysText(days: number): string {
  if (days === 0) return "today";
  const n = Math.abs(days);
  const unit = `${n} day${n === 1 ? "" : "s"}`;
  return days > 0 ? `in ${unit}` : `${unit} ago`;
}

export const STATE: Record<
  AccessStateName | string,
  { label: string; tone: "ok" | "warn" | "bad" | "info" | "accent" }
> = {
  trialing: { label: "On trial", tone: "info" },
  active: { label: "Paying", tone: "ok" },
  grace: { label: "Overdue (grace)", tone: "warn" },
  read_only: { label: "Read-only", tone: "bad" },
  suspended: { label: "Suspended", tone: "bad" },
  complimentary: { label: "Free", tone: "accent" },
};

export const INVOICE_STATUS: Record<
  string,
  { label: string; tone: "ok" | "warn" | "bad" | "info" }
> = {
  issued: { label: "Waiting for payment", tone: "warn" },
  paid: { label: "Paid", tone: "ok" },
  void: { label: "Void", tone: "bad" },
};

export const METHOD: Record<string, string> = {
  mpesa: "M-Pesa",
  bank: "Bank transfer",
  card: "Card",
  manual: "Recorded by hand",
  other: "Other",
};

/** A date input's value (2026-10-31) as an ISO time at the end of that Nairobi day, for "paid until". */
export function endOfDay(day: string): string {
  return new Date(`${day}T23:59:59+03:00`).toISOString();
}

/** An ISO time as a date input's value, in Nairobi. */
export function dayValue(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("en-CA", { timeZone: "Africa/Nairobi" }) : "";
}

const ACTION_WORDS: Record<string, string> = {
  "platform.subscription_edited": "Edited the subscription",
  "platform.subscription_advanced": "Advanced the renewal",
  "platform.subscription_cancelled": "Cancelled the subscription",
  "platform.subscription_reactivated": "Reactivated the subscription",
  "platform.vehicle_plan_changed": "Changed a vehicle's plan",
  "platform.invoice_raised": "Raised an invoice",
  "platform.invoice_voided": "Voided an invoice",
  "platform.invoice_marked_paid": "Marked an invoice paid",
  "platform.reminder_sent": "Sent a renewal reminder",
  "platform.business_edited": "Corrected the business details",
  "platform.trial_extended": "Extended the trial",
  "platform.complimentary_set": "Changed the free-account setting",
  "platform.suspended": "Put the account on hold",
  "platform.unsuspended": "Lifted the hold",
  "platform.custom_price_set": "Set an agreed price",
  "platform_etims.submitted": "Tax invoice filed with KRA",
  "platform_etims.retried": "Retried a tax invoice",
  "platform_etims.resolved_by_hand": "Handled a tax invoice by hand",
  "subscription.paid": "Subscription paid",
  "subscription.cancelled": "Customer cancelled",
  "subscription.reactivated": "Customer reactivated",
  "subscription.invoice_raised": "Customer raised an invoice",
  "subscription.plans_changed": "Customer changed plans",
  "subscription.duplicate_card_payment": "Duplicate card payment: refund needed",
  "subscription.card_payment_started": "Card payment started",
  "subscription.payment_requested": "M-Pesa payment requested",
  "subscription.sms_bundle_invoiced": "Text bundle invoiced",
  "note.added": "Added a note",
  "note.edited": "Edited a note",
  "note.deleted": "Deleted a note",
  "admin.granted": "Gave someone the console",
  "admin.revoked": "Took the console away",
  "feedback.read": "Marked feedback read",
  "feedback.resolved": "Resolved feedback",
  "feedback.new": "Reopened feedback",
  "support.entered": "Entered the account with support access",
  "support.left": "Left the account",
};

export const actionText = (action: string) => ACTION_WORDS[action] ?? action;
