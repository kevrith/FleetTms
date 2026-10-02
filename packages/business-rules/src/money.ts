import type { Cents } from "@fleettms/types";

export const kesToCents = (kes: number): Cents => Math.round(kes * 100);
export const centsToKes = (cents: Cents): number => cents / 100;

export function formatKes(cents: Cents): string {
  return `KES ${centsToKes(cents).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
