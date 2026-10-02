export type FuelFlag = "amount_mismatch" | "no_receipt";

const MPESA = /^[A-Z0-9]{10}$/;

/** An M-Pesa code is 10 capital letters and numbers. Returns the tidied code, or null if it is not one. */
export function normalizeMpesaCode(raw: string): string | null {
  const code = raw.trim().toUpperCase();
  return MPESA.test(code) ? code : null;
}

/** Reasons a fuel entry deserves a second look. They never stop it being recorded. */
export function fuelFlags(input: {
  litres: number;
  priceCents: number;
  amountCents: number;
  hasReceipt: boolean;
}): FuelFlag[] {
  const flags: FuelFlag[] = [];
  const expected = input.litres * input.priceCents;
  if (Math.abs(expected - input.amountCents) > Math.max(100, input.amountCents / 100)) {
    flags.push("amount_mismatch");
  }
  if (!input.hasReceipt) flags.push("no_receipt");
  return flags;
}
