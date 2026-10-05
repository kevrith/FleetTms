import { UserPlus } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { date } from "./format";
import { Badge, DataTable, FormDialog, FormField, Page, Panel, useLoad, useToast } from "./kit";

/** Who runs the console. Everyone here can see every customer's subscription and change it, so keep the list short. */
export default function Admins() {
  const { data, error, reload } = useLoad(() => api.platformAdmins());
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const toast = useToast();

  async function remove(id: string, name: string) {
    if (
      !window.confirm(
        `Take the console away from ${name}? Any support session they have open ends.`,
      )
    )
      return;
    try {
      await api.platformRemoveAdmin(id);
      await reload();
      toast.ok(`${name} no longer has the console.`);
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "That did not work.");
    }
  }

  return (
    <Page
      title="Platform admins"
      subtitle="People who can use this console. Each needs an account with two-step sign-in."
      actions={
        <button
          className="pf-btn primary"
          onClick={() => {
            setEmail("");
            setAdding(true);
          }}
        >
          <UserPlus size={15} /> Add an admin
        </button>
      }
    >
      <ErrorBanner message={error} />
      <Panel flush>
        <DataTable
          rows={data ?? []}
          rowKey={(a) => a.id}
          empty="No admins."
          columns={[
            {
              key: "n",
              header: "Name",
              render: (a) => (
                <>
                  <strong>{a.name}</strong> {a.you && <Badge tone="accent">you</Badge>}
                </>
              ),
            },
            { key: "e", header: "Email", render: (a) => a.email ?? "none" },
            { key: "p", header: "Phone", render: (a) => a.phone ?? "none" },
            { key: "c", header: "Account since", render: (a) => date(a.created_at) },
            {
              key: "a",
              header: "",
              render: (a) =>
                a.you ? null : (
                  <button className="pf-btn small danger" onClick={() => void remove(a.id, a.name)}>
                    Remove
                  </button>
                ),
            },
          ]}
        />
      </Panel>
      {adding && (
        <FormDialog
          title="Add an admin"
          description="They must already have a FleetTms account (they can sign up first). They can use the console as soon as you save."
          submitLabel="Give access"
          onClose={() => setAdding(false)}
          onSubmit={async () => {
            await api.platformAddAdmin(email.trim());
            await reload();
            toast.ok("Access given.");
          }}
        >
          <FormField label="Their email address">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </FormField>
        </FormDialog>
      )}
    </Page>
  );
}
