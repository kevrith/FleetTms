import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { actionText, dateTime } from "./format";
import { Badge, Chips, Empty, Page, Pager, Panel, useLoad } from "./kit";

/** What the platform has done: changes to customers' accounts (also in each customer's own trail) and the platform's own actions. */
export default function AuditLog() {
  const [source, setSource] = useState("all");
  const [days, setDays] = useState("30");
  const [action, setAction] = useState("");
  const [typed, setTyped] = useState("");
  const [page, setPage] = useState(1);
  const { data, error } = useLoad(
    () => api.platformAudit({ source, days: Number(days), action, page, page_size: 50 }),
    [source, days, action, page],
  );
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Page
      title="Audit log"
      subtitle="Who did what to which customer, and when. Notes and admin changes are only here; account changes are in the customer's own trail too."
    >
      <ErrorBanner message={error} />
      <Panel flush>
        <div className="pf-tablebar">
          <Chips
            value={source}
            onChange={(s) => {
              setSource(s);
              setPage(1);
            }}
            options={[
              { id: "all", label: "Everything" },
              { id: "customers", label: "Customer accounts" },
              { id: "platform", label: "Platform only" },
            ]}
          />
          <select
            aria-label="Period"
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
              setPage(1);
            }}
          >
            {[1, 7, 30, 90, 365, 730].map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setAction(typed.trim());
              setPage(1);
            }}
            style={{ marginLeft: "auto" }}
          >
            <input
              type="search"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Action starts with, e.g. platform.invoice"
              aria-label="Action"
              style={{ minWidth: 280 }}
            />
          </form>
        </div>
        {data && data.rows.length === 0 && <Empty>Nothing in that period.</Empty>}
        {data && data.rows.length > 0 && (
          <div className="pf-scroll">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>What</th>
                  <th>Customer</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr>
                      <td>{dateTime(r.at)}</td>
                      <td>{r.actor ?? "System"}</td>
                      <td>
                        <strong>{actionText(r.action)}</strong>{" "}
                        <Badge tone={r.source === "platform" ? "accent" : undefined}>
                          {r.source === "platform" ? "platform" : "account"}
                        </Badge>
                        {r.note && <div className="pf-muted">{r.note}</div>}
                      </td>
                      <td>
                        {r.business_id ? (
                          <Link to={`/platform/customers/${r.business_id}`}>{r.business}</Link>
                        ) : (
                          <span className="pf-muted">none</span>
                        )}
                      </td>
                      <td>
                        {(r.before || r.after) && (
                          <button
                            className="pf-btn small"
                            aria-expanded={open === r.id}
                            onClick={() => setOpen(open === r.id ? null : r.id)}
                          >
                            Details
                          </button>
                        )}
                      </td>
                    </tr>
                    {open === r.id && (
                      <tr>
                        <td colSpan={5}>
                          {r.before && (
                            <div className="pf-diff">Before: {JSON.stringify(r.before)}</div>
                          )}
                          {r.after && (
                            <div className="pf-diff">After: {JSON.stringify(r.after)}</div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > data.page_size && (
          <Pager
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPage={setPage}
          />
        )}
      </Panel>
    </Page>
  );
}
