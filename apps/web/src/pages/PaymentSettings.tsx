import type { PaymentSettings } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { reminderStep } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/** Where clients pay, when they are reminded, and how invoices go to KRA eTIMS. */
export default function PaymentSettingsPage() {
  const { can } = useAuth();
  const [s, setS] = useState<PaymentSettings | null>(null);
  const [steps, setSteps] = useState("");
  const [simulate, setSimulate] = useState({ amount: "", ref: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = can("business.manage");
  const load = useCallback(async () => {
    try {
      const got = await api.paymentSettings();
      setS(got);
      setSteps(got.reminder_offsets.join(", "));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!s) return <ErrorBanner message={error} />;
  const set = (patch: Partial<PaymentSettings>) => setS({ ...s, ...patch });
  const offsets = steps
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number);
  const badSteps = offsets.some((n) => !Number.isInteger(n));
  async function save() {
    await run(
      () =>
        api.savePaymentSettings({
          shortcode: s!.shortcode || null,
          shortcode_type: s!.shortcode_type,
          reminders_enabled: s!.reminders_enabled,
          reminder_offsets: offsets,
          reminder_channels: s!.reminder_channels,
          etims_enabled: s!.etims_enabled,
          etims_branch_id: s!.etims_branch_id,
          etims_device_serial: s!.etims_device_serial || null,
          etims_zero_vat_code: s!.etims_zero_vat_code,
          etims_item_code: s!.etims_item_code,
          etims_item_class_code: s!.etims_item_class_code,
          etims_pkg_unit: s!.etims_pkg_unit,
          etims_qty_unit: s!.etims_qty_unit,
          kra_pin: s!.kra_pin || null,
        }),
      "Saved.",
    );
  }
  const channel = (c: "sms" | "email") => (
    <label className="field" key={c}>
      <span>
        <input
          type="checkbox"
          disabled={!editable}
          checked={s.reminder_channels.includes(c)}
          onChange={(e) =>
            set({
              reminder_channels: e.target.checked
                ? [...s.reminder_channels, c]
                : s.reminder_channels.filter((x) => x !== c),
            })
          }
        />{" "}
        {c === "sms" ? "SMS" : "Email (with the invoice attached)"}
      </span>
    </label>
  );
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      {!editable && <p className="muted">Only the owner can change these settings.</p>}
      <Card title="Where clients pay (M-Pesa)">
        <div className="form-grid">
          <Field label="Type">
            <select
              disabled={!editable}
              value={s.shortcode_type}
              onChange={(e) => set({ shortcode_type: e.target.value as "paybill" | "till" })}
            >
              <option value="paybill">Paybill</option>
              <option value="till">Buy Goods Till</option>
            </select>
          </Field>
          <Field label="Paybill or Till number">
            <input
              disabled={!editable}
              value={s.shortcode ?? ""}
              onChange={(e) => set({ shortcode: e.target.value })}
            />
          </Field>
        </div>
        <p className="muted">
          Clients type the invoice number (for example INV-0001) as the account number, and the
          payment is put against that invoice by itself.{" "}
          {s.urls_registered_at
            ? `Safaricom knows where to send payments (registered ${new Date(s.urls_registered_at).toLocaleDateString("en-KE")}).`
            : "Safaricom has not been told where to send payments yet."}
          {!s.daraja_live &&
            " No Safaricom keys are set, so a stand-in is used and nothing real is sent."}
        </p>
        {editable && (
          <p className="actions">
            <button
              className="btn"
              disabled={!s.shortcode}
              onClick={() => run(() => api.registerDarajaUrls(), "Safaricom has the address.")}
            >
              Register with Safaricom
            </button>
          </p>
        )}
        {editable && s.can_simulate && (
          <div className="form-grid">
            <Field label="Try a test payment (KES)">
              <input
                type="number"
                min="1"
                value={simulate.amount}
                onChange={(e) => setSimulate({ ...simulate, amount: e.target.value })}
              />
            </Field>
            <Field label="Account number, for example INV-0001">
              <input
                value={simulate.ref}
                onChange={(e) => setSimulate({ ...simulate, ref: e.target.value })}
              />
            </Field>
            <button
              className="btn"
              disabled={!(Number(simulate.amount) > 0) || !s.shortcode}
              onClick={() =>
                run(
                  () =>
                    api.simulatePayment(Math.round(Number(simulate.amount) * 100), simulate.ref),
                  "Test payment sent. See M-Pesa payments.",
                )
              }
            >
              Send test payment
            </button>
          </div>
        )}
      </Card>
      <Card title="Payment reminders">
        <label className="field">
          <span>
            <input
              type="checkbox"
              disabled={!editable}
              checked={s.reminders_enabled}
              onChange={(e) => set({ reminders_enabled: e.target.checked })}
            />{" "}
            Remind clients about unpaid invoices automatically
          </span>
        </label>
        {channel("sms")}
        {channel("email")}
        <Field label="When (days from the due date, minus is before; for example -3, 1, 7, 14, 30)">
          <input disabled={!editable} value={steps} onChange={(e) => setSteps(e.target.value)} />
        </Field>
        {!badSteps && offsets.length > 0 && (
          <p className="muted">
            {[...offsets]
              .sort((a, b) => a - b)
              .map(reminderStep)
              .join("; ")}
            .
          </p>
        )}
        <p className="muted">
          Each reminder goes once. You can switch reminders off for a single client on their page.
        </p>
      </Card>
      <Card title="KRA eTIMS">
        <label className="field">
          <span>
            <input
              type="checkbox"
              disabled={!editable}
              checked={s.etims_enabled}
              onChange={(e) => set({ etims_enabled: e.target.checked })}
            />{" "}
            Send every invoice to KRA eTIMS
          </span>
        </label>
        <div className="form-grid">
          <Field label="Business KRA PIN">
            <input
              disabled={!editable}
              value={s.kra_pin ?? ""}
              onChange={(e) => set({ kra_pin: e.target.value })}
            />
          </Field>
          <Field label="Branch ID">
            <input
              disabled={!editable}
              value={s.etims_branch_id}
              onChange={(e) => set({ etims_branch_id: e.target.value })}
            />
          </Field>
          <Field label="Device serial number from KRA">
            <input
              disabled={!editable}
              value={s.etims_device_serial ?? ""}
              onChange={(e) => set({ etims_device_serial: e.target.value })}
            />
          </Field>
          <Field label="Tax code for invoices with no VAT">
            <select
              disabled={!editable}
              value={s.etims_zero_vat_code}
              onChange={(e) => set({ etims_zero_vat_code: e.target.value as "A" | "C" | "D" })}
            >
              <option value="A">A: Exempt</option>
              <option value="C">C: Zero-rated</option>
              <option value="D">D: Not a VAT item</option>
            </select>
          </Field>
          <Field label="Service item code">
            <input
              disabled={!editable}
              value={s.etims_item_code}
              onChange={(e) => set({ etims_item_code: e.target.value })}
            />
          </Field>
          <Field label="Item classification code">
            <input
              disabled={!editable}
              value={s.etims_item_class_code}
              onChange={(e) => set({ etims_item_class_code: e.target.value })}
            />
          </Field>
        </div>
        <p className="muted">
          {s.etims_connected_at
            ? `Device connected ${new Date(s.etims_connected_at).toLocaleDateString("en-KE")}.`
            : "Save, then connect the device to check it with KRA."}
          {!s.etims_live &&
            " No KRA address is set, so a stand-in is used and nothing real is sent."}{" "}
          Check the tax code and item codes with your accountant before going live.
        </p>
        {editable && (
          <p className="actions">
            <button
              className="btn"
              disabled={!s.etims_enabled}
              onClick={() => run(() => api.etimsConnect(), "Device connected to KRA.")}
            >
              Connect the device
            </button>
          </p>
        )}
      </Card>
      {editable && (
        <p className="actions">
          <button className="btn primary" disabled={badSteps} onClick={save}>
            Save
          </button>
        </p>
      )}
    </>
  );
}
