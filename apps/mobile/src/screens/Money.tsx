import { formatKes } from "@fleettms/business-rules";
import type {
  Expense,
  FloatTransfer,
  Reconciliation,
  ReconciliationDetail,
  StaffProfile,
} from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { floatDraft } from "../money";
import { Body, Button, ErrorText, errorMessage, Input, Screen, Title, useTheme } from "../ui";

const CATEGORY: Record<string, string> = {
  police_county: "Police and county fees",
  loading: "Loading and offloading",
};
const FLAG: Record<string, string> = {
  over_limit: "Over the spend limit",
  unusual_for_route: "Unusual for this route",
  no_receipt: "No receipt or M-Pesa code",
};
const label = (category: string) =>
  CATEGORY[category] ?? category.charAt(0).toUpperCase() + category.slice(1).replace(/_/g, " ");
const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

function Card({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ padding: 14, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}>
      {children}
    </View>
  );
}

function Heading({ children }: { children: string }) {
  const t = useTheme();
  return <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>{children}</Text>;
}

/** Expenses that went over a spend limit. They do not count until the owner decides. */
function ExpensesWaiting({ names, onChange }: { names: Map<string, string>; onChange: () => void }) {
  const [rows, setRows] = useState<Expense[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.expenses({ status: "awaiting_approval" }));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function decide(e: Expense, approve: boolean) {
    setBusy(e.id);
    setError(null);
    try {
      await api.decideExpense(e.id, approve);
      await load();
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <Heading>Expenses over the limit</Heading>
      <ErrorText message={error} />
      {rows?.length === 0 && <Body muted>None waiting.</Body>}
      {rows?.map((e) => (
        <Card key={e.id}>
          <Body>
            {label(e.category)}, {formatKes(e.amount_cents)}
          </Body>
          <Body muted>
            {(e.driver_membership_id && names.get(e.driver_membership_id)) || "Driver"}, {day(e.spent_at)}
            {e.note ? `. ${e.note}` : ""}
          </Body>
          {e.flags.map((f) => (
            <Body key={f} muted>
              {FLAG[f] ?? f}
            </Body>
          ))}
          <Button label="Approve" onPress={() => void decide(e, true)} busy={busy === e.id} />
          <Button
            label="Reject"
            kind="danger"
            onPress={() => void decide(e, false)}
            disabled={busy !== null}
          />
        </Card>
      ))}
    </>
  );
}

/** One driver's day: opening + floats - expenses = closing. Approve it, or send it back with a reason. */
function SheetDetail({ id, onDone, onBack }: { id: string; onDone: () => void; onBack: () => void }) {
  const [sheet, setSheet] = useState<ReconciliationDetail | null>(null);
  const [action, setAction] = useState<"carry_forward" | "returned">("carry_forward");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .reconciliation(id)
      .then(setSheet)
      .catch((e) => setError(errorMessage(e)));
  }, [id]);

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (approve) await api.approveReconciliation(id, action, note.trim() || undefined);
      else await api.rejectReconciliation(id, note.trim());
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button label="Back" kind="secondary" onPress={onBack} disabled={busy} />
      <ErrorText message={error} />
      {sheet && (
        <Card>
          <Title>{sheet.driver_name}</Title>
          <Body muted>{day(sheet.day)}</Body>
          <Body>Opening {formatKes(sheet.opening_cents)}</Body>
          <Body>Floats received {formatKes(sheet.floats_cents)}</Body>
          <Body>Expenses {formatKes(sheet.expenses_cents)}</Body>
          <Body>Closing balance {formatKes(sheet.closing_cents)}</Body>
          {sheet.expenses.map((e) => (
            <Body key={e.id} muted>
              {label(e.category)}, {formatKes(e.amount_cents)}
              {e.note ? `, ${e.note}` : ""}
            </Body>
          ))}
          {sheet.pending_expenses > 0 && (
            <Body>
              {sheet.pending_expenses} expense{sheet.pending_expenses === 1 ? " is" : "s are"} still
              waiting for you. Decide on them first, then approve the day.
            </Body>
          )}
          {sheet.status === "submitted" && (
            <>
              <Body muted>What happens to the balance?</Body>
              <Button
                label="Carry it forward to tomorrow"
                kind={action === "carry_forward" ? "primary" : "secondary"}
                onPress={() => {
                  setAction("carry_forward");
                  setError(null);
                }}
              />
              <Button
                label="The driver returned the cash"
                kind={action === "returned" ? "primary" : "secondary"}
                onPress={() => {
                  setAction("returned");
                  setError(null);
                }}
              />
              <Input
                label="Note (needed to send it back)"
                value={note}
                onChangeText={setNote}
                maxLength={255}
              />
              <Button
                label="Approve the day"
                onPress={() => void decide(true)}
                busy={busy}
                disabled={sheet.pending_expenses > 0}
              />
              <Button
                label="Send back to the driver"
                kind="danger"
                onPress={() => void decide(false)}
                disabled={busy || note.trim().length < 3}
              />
            </>
          )}
        </Card>
      )}
    </>
  );
}

function SheetsWaiting({
  refresh,
  open,
  setOpen,
}: {
  refresh: number;
  open: string | null;
  setOpen: (id: string | null) => void;
}) {
  const [rows, setRows] = useState<Reconciliation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.reconciliations("submitted"));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, refresh]);

  if (open) {
    return (
      <SheetDetail
        id={open}
        onBack={() => setOpen(null)}
        onDone={() => {
          setOpen(null);
          void load();
        }}
      />
    );
  }
  return (
    <>
      <Heading>Daily reports from drivers</Heading>
      <ErrorText message={error} />
      {rows?.length === 0 && <Body muted>None waiting.</Body>}
      {rows?.map((r) => (
        <Card key={r.id}>
          <Body>
            {r.driver_name}, {day(r.day)}
          </Body>
          <Body muted>
            Spent {formatKes(r.expenses_cents)}, balance {formatKes(r.closing_cents)}
          </Body>
          <Button label="Open" kind="secondary" onPress={() => setOpen(r.id)} />
        </Card>
      ))}
    </>
  );
}

/** Record money sent to a driver. The money moves in M-Pesa as usual; this keeps the driver's balance right. */
function SendFloat({ staff }: { staff: StaffProfile[] }) {
  const [driverId, setDriverId] = useState<string | null>(null);
  const [kes, setKes] = useState("");
  const [mpesaCode, setMpesaCode] = useState("");
  const [note, setNote] = useState("");
  const [recent, setRecent] = useState<FloatTransfer[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const crew = staff.filter(
    (s) => s.status === "active" && (s.roles.includes("driver") || s.roles.includes("turnboy")),
  );
  const nameOf = (id: string) => staff.find((s) => s.membership_id === id)?.name ?? "Driver";

  const load = useCallback(async () => {
    try {
      setRecent((await api.floats()).slice(0, 8));
    } catch {
      /* the list is a convenience */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function send() {
    const draft = floatDraft({ driverId, kes, mpesaCode, note });
    setSaved(null);
    if (!draft.ok) {
      setError(draft.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.sendFloat(draft.input);
      setSaved(`${formatKes(draft.input.amount_cents)} recorded for ${nameOf(draft.input.driver_membership_id)}.`);
      setKes("");
      setMpesaCode("");
      setNote("");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading>Record a float</Heading>
      <Body muted>Send the money by M-Pesa as usual, then record it here.</Body>
      {crew.length === 0 && <Body muted>No active drivers or turnboys yet.</Body>}
      {crew.map((s) => (
        <Button
          key={s.membership_id}
          label={s.name}
          kind={driverId === s.membership_id ? "primary" : "secondary"}
          onPress={() => setDriverId(s.membership_id)}
        />
      ))}
      <Input label="Amount (KES)" value={kes} onChangeText={setKes} keyboardType="decimal-pad" />
      <Input
        label="M-Pesa code (optional)"
        value={mpesaCode}
        onChangeText={setMpesaCode}
        autoCapitalize="characters"
        maxLength={10}
      />
      <Input label="Note (optional)" value={note} onChangeText={setNote} maxLength={255} />
      <ErrorText message={error} />
      {saved && <Body>{saved}</Body>}
      <Button label="Record the float" onPress={() => void send()} busy={busy} />
      {recent.length > 0 && <Heading>Recent floats</Heading>}
      {recent.map((f) => (
        <Body key={f.id} muted>
          {nameOf(f.driver_membership_id)}: {formatKes(f.amount_cents)}, {day(f.sent_at)}
          {f.mpesa_code ? `, ${f.mpesa_code}` : ""}
        </Body>
      ))}
    </>
  );
}

/** The owner's money on the phone: approve what drivers send in, and record the floats going out. */
export default function MoneyScreen() {
  const { me } = useAuth();
  const can = (p: string) => me?.permissions.includes(p) ?? false;
  const canExpenses = can("expenses.approve_limit");
  const canSheets = can("reconciliations.approve");
  const canFloats = can("floats.manage");
  const [tab, setTab] = useState<"approve" | "float">(canExpenses || canSheets ? "approve" : "float");
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  // A day report open on its own: the rest of the screen steps aside while the owner decides.
  const [openSheet, setOpenSheet] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!can("staff.view")) return;
    api
      .staff()
      .then(setStaff)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const names = new Map(staff.map((s) => [s.membership_id, s.name]));

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ gap: 12, paddingVertical: 16 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              setRefresh((n) => n + 1);
              setTimeout(() => setRefreshing(false), 600);
            }}
          />
        }
      >
        <Title>Money</Title>
        {(canExpenses || canSheets) && canFloats && !openSheet && (
          <>
            <Button
              label="To approve"
              kind={tab === "approve" ? "primary" : "secondary"}
              onPress={() => setTab("approve")}
            />
            <Button
              label="Send a float"
              kind={tab === "float" ? "primary" : "secondary"}
              onPress={() => setTab("float")}
            />
          </>
        )}
        {tab === "approve" && (
          <>
            {canExpenses && !openSheet && (
              <ExpensesWaiting key={refresh} names={names} onChange={() => setRefresh((n) => n + 1)} />
            )}
            {canSheets && <SheetsWaiting refresh={refresh} open={openSheet} setOpen={setOpenSheet} />}
          </>
        )}
        {tab === "float" && canFloats && <SendFloat staff={staff} />}
      </ScrollView>
    </Screen>
  );
}
