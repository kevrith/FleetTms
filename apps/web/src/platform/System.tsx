import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { dateTime } from "./format";
import { Badge, Page, Panel, Stat, useLoad } from "./kit";

const CHECK_NAMES: Record<string, string> = {
  database: "Database",
  redis: "Job queue (Redis)",
  storage: "File storage",
  worker: "Background worker",
  base_backup: "Daily backup",
  wal_archive: "Continuous backup",
};
const STUCK: Record<string, string> = {
  etims_review: "Tax invoices KRA refused or that keep failing",
  etims_waiting: "Tax invoices waiting to be sent",
  whatsapp_failed_24h: "WhatsApp messages that failed today",
  reminders_failed_24h: "Payment reminders that failed today",
  card_payments_pending: "Card payments started over an hour ago and not answered",
};
const INTEGRATIONS: Record<string, string> = {
  sms: "Text messages",
  etims_platform: "Our tax invoices (KRA)",
  storage: "File storage",
  cards: "Card payments (Paystack)",
  whatsapp: "WhatsApp Business",
  mpesa: "M-Pesa subscription payments",
};

/** Is everything working, and what is stuck. */
export default function System() {
  const { data, error, loading, reload } = useLoad(() => api.platformSystem());
  return (
    <Page
      title="System status"
      subtitle="The same checks the uptime monitor makes, plus what is waiting on a person."
      actions={
        <button className="pf-btn" onClick={() => void reload()} disabled={loading}>
          <RefreshCw size={15} /> Check again
        </button>
      }
    >
      <ErrorBanner message={error} />
      {data && (
        <>
          <div className="pf-grid cols-4">
            <Stat
              label="Overall"
              tone={data.ready ? "ok" : "bad"}
              value={data.ready ? "Ready" : "Not ready"}
              hint={
                data.failing.length ? `Failing: ${data.failing.join(", ")}` : "every check passes"
              }
            />
            <Stat label="Queue" value={data.queue.waiting ?? "n/a"} hint="jobs waiting" />
            <Stat
              label="Worker heartbeat"
              tone={
                data.queue.worker_heartbeat_seconds === null ||
                data.queue.worker_heartbeat_seconds > 180
                  ? "bad"
                  : "ok"
              }
              value={
                data.queue.worker_heartbeat_seconds === null
                  ? "none"
                  : `${data.queue.worker_heartbeat_seconds}s ago`
              }
            />
            <Stat
              label="Version"
              value={data.version}
              hint={`${data.environment}, checked ${dateTime(data.checked_at)}`}
            />
          </div>
          <Panel title="Checks">
            <div className="pf-checks">
              {Object.entries(data.checks).map(([k, c]) => (
                <div key={k} className={`pf-check${c.ok ? "" : " bad"}`}>
                  <span className="dot" />
                  <strong>{CHECK_NAMES[k] ?? k}</strong>
                  <small>{c.ok ? (c.state ?? c.backend ?? "working") : c.reason}</small>
                </div>
              ))}
            </div>
          </Panel>
          <div className="pf-grid cols-2">
            <Panel title="Waiting on a person">
              <dl className="pf-kv">
                {Object.entries(data.stuck).map(([k, n]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt style={{ gridColumn: "1 / 2" }}>{n}</dt>
                    <dd>{STUCK[k] ?? k}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
            <Panel title="Integrations">
              <dl className="pf-kv">
                {Object.entries(data.integrations).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{INTEGRATIONS[k] ?? k}</dt>
                    <dd>
                      {typeof v === "boolean" ? (
                        <Badge tone={v ? "ok" : "warn"}>{v ? "Set up" : "Not set up"}</Badge>
                      ) : (
                        <Badge tone="info">{v}</Badge>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>
        </>
      )}
    </Page>
  );
}
