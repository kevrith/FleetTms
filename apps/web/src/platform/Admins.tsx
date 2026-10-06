import { UserPlus } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { date } from "./format";
import { Badge, DataTable, FormDialog, FormField, Page, Panel, useLoad, useToast } from "./kit";

/** Who runs the console. Everyone here can see every customer's subscription and change it, so keep the list short.
 * Only a super admin adds or removes admins, and a super admin cannot be removed here. */
export default function Admins() {
  const { data, error, reload } = useLoad(() => api.platformAdmins());
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const toast = useToast();
  const iAmSuper = data?.find((a) => a.you)?.super ?? false;

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
      subtitle={
        iAmSuper
          ? "People who can use this console. Each needs an account with two-step sign-in."
          : "People who can use this console. Only a super admin can add or remove admins."
      }
      actions={
        iAmSuper ? (
          <button
            className="pf-btn primary"
            onClick={() => {
              setEmail("");
              setAdding(true);
            }}
          >
            <UserPlus size={15} /> Add an admin
          </button>
        ) : undefined
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
                  <strong>{a.name}</strong> {a.super && <Badge tone="accent">super admin</Badge>}{" "}
                  {a.you && <Badge tone="accent">you</Badge>}
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
                a.you || a.super || !iAmSuper ? null : (
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
