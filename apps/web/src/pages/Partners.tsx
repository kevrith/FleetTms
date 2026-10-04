import type { PartnerRow } from "@fleettms/types";
import { Download } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

/** The platform admin's side of the partner programme: decide applications, set shares, settle what is owed. */
export default function Partners() {
  const [rows, setRows] = useState<PartnerRow[]>([]);
  const [text, setText] = useState<Record<string, string>>({});
  const [key, setKey] = useState<{ name: string; key: string } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.partners());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await work();
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function download() {
    try {
      const url = URL.createObjectURL(await api.partnerCommissionsFile());
      const a = document.createElement("a");
      a.href = url;
      a.download = "partner-commissions.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const owed = rows.reduce((n, r) => n + r.owed_cents, 0);
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      {key && (
        <p className="banner ok">
          {key.name}: the private key is <strong>{key.key}</strong>. It was also texted to them and
          is shown only now.
        </p>
      )}
      <Card title="Partners">
        <p>
          Installers who bring customers earn a share of what those customers pay. Owed in total:{" "}
          <strong>{kes(owed)}</strong>.{" "}
          <button className="btn" type="button" onClick={download}>
            <Download size={16} /> What is owed (spreadsheet)
          </button>
        </p>
        {rows.length === 0 && <p className="muted">No applications yet.</p>}
        <ul className="list">
          {rows.map((p) => (
            <li key={p.id}>
              <span>
                <strong>{p.name}</strong>{" "}
                <span
                  className={`status ${p.status === "approved" ? "ok" : p.status === "pending" ? "warn" : "bad"}`}
                >
                  {p.status}
                </span>
                <br />
                <span className="muted">
                  {p.contact_name}, {p.phone} {p.city ? `, ${p.city}` : ""}. Applied{" "}
                  {nairobiTime(p.created_at)}.
                </span>
                {p.message && (
                  <>
                    <br />
                    <span className="muted">"{p.message}"</span>
                  </>
                )}
                {p.status !== "pending" && (
                  <>
                    <br />
                    Code <strong>{p.code}</strong>, {p.commission_pct}%. {p.referred} referred,{" "}
                    {p.paying} paying. Owed {kes(p.owed_cents)}, paid {kes(p.paid_cents)}.
                  </>
                )}
              </span>
              <span className="actions">
                {p.status === "pending" && (
                  <>
                    <button
                      className="btn primary"
                      type="button"
                      onClick={() =>
                        act(async () => {
                          const r = await api.approvePartner(p.id);
                          setKey({ name: p.name, key: r.portal_key });
                        }, "Approved. Their code and key were texted to them.")
                      }
                    >
                      Approve
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        window.confirm("Delete this application?") &&
                        act(() => api.partnerAction(p.id, "reject"), "Application removed.")
                      }
                    >
                      Reject
                    </button>
                  </>
                )}
                {p.status === "approved" && (
                  <>
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(
                          () => api.partnerAction(p.id, "suspend"),
                          "Suspended: no new referrals or commission.",
                        )
                      }
                    >
                      Suspend
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(async () => {
                          const r = await api.reissuePartnerKey(p.id);
                          setKey({ name: p.name, key: r.portal_key });
                        }, "A new key was made and texted. The old one no longer works.")
                      }
                    >
                      New key
                    </button>
                    {p.owed_cents > 0 && (
                      <>
                        <input
                          aria-label="Payment reference"
                          placeholder="M-Pesa code or bank reference"
                          value={text[p.id] ?? ""}
                          onChange={(e) => setText({ ...text, [p.id]: e.target.value })}
                        />
                        <button
                          className="btn"
                          type="button"
                          disabled={(text[p.id] ?? "").trim().length < 3}
                          onClick={() =>
                            act(() => api.payPartner(p.id, text[p.id] ?? ""), "Marked as paid.")
                          }
                        >
                          Mark {kes(p.owed_cents)} paid
                        </button>
                      </>
                    )}
                  </>
                )}
                {p.status === "suspended" && (
                  <button
                    className="btn"
                    type="button"
                    onClick={() => act(() => api.partnerAction(p.id, "reactivate"), "Reactivated.")}
                  >
                    Reactivate
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
