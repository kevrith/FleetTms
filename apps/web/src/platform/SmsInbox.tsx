import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { dateTime } from "./format";
import { Badge, DataTable, Page, Panel, useLoad } from "./kit";

const codeIn = (message: string) => /\b\d{6}\b/.exec(message)?.[0] ?? "";

/** The sign-in and verification codes the system has "sent" in the last half hour. Until a real text gateway (Africa's Talking) is
 * set up nothing leaves the server, so this is where a super admin reads a code to finish signing in while testing. Looking is logged. */
export default function SmsInbox() {
  const { data, error, loading, reload } = useLoad(() => api.platformSmsInbox());
  return (
    <Page
      title="Text codes (testing)"
      subtitle="One-time codes the system would have texted, until a real text gateway is set up."
      actions={
        <button className="pf-btn" onClick={() => void reload()} disabled={loading}>
          <RefreshCw size={15} /> Refresh
        </button>
      }
    >
      <ErrorBanner message={error} />
      {data && !data.active && (
        <Panel title="Nothing to show">
          <p>
            Texts are being sent through a real gateway, so no code is kept here. This page only
            works while no gateway is set up.
          </p>
        </Panel>
      )}
      {data?.active && (
        <>
          <p className="pf-muted">
            Codes from the last {data.minutes} minutes, newest first. A code lets whoever has it
            sign in as that person, so use it only to test, and each look that shows a code is
            written to the audit log. A restart of the server clears this list.
          </p>
          <Panel flush>
            <DataTable
              rows={data.messages}
              rowKey={(m) => m.at + m.to}
              empty="No code has been sent in the last half hour. Ask for one, then press Refresh."
              columns={[
                {
                  key: "code",
                  header: "Code",
                  render: (m) => <Badge tone="accent">{codeIn(m.message)}</Badge>,
                },
                { key: "to", header: "Sent to", render: (m) => m.to },
                { key: "at", header: "When", render: (m) => dateTime(m.at) },
              ]}
            />
          </Panel>
        </>
      )}
    </Page>
  );
}
