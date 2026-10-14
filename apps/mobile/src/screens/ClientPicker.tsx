import type { DeliveryClient } from "@fleettms/types";
import { useEffect, useState } from "react";
import { View } from "react-native";
import { api } from "../api";
import { Body, Button, Input } from "../ui";

/** Who the delivery is for, and where at that client. Nothing, an existing client (with one of its saved places), or a new client name. */
export interface ClientChoice {
  clientId: string | null;
  siteId: string | null;
  newName: string | null;
}
export const noClient: ClientChoice = { clientId: null, siteId: null, newName: null };
export const hasClient = (c: ClientChoice) => c.clientId !== null || c.newName !== null;

const MAX_SHOWN = 5;

/** Picks from the business's clients (needs a connection, like making the trip). If the list cannot be loaded the trip can still be made. */
export function ClientPicker({
  value,
  onChange,
}: {
  value: ClientChoice;
  onChange: (c: ClientChoice) => void;
}) {
  const [clients, setClients] = useState<DeliveryClient[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let live = true;
    api
      .myClients()
      .then((rows) => live && setClients(rows))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  const picked = clients?.find((c) => c.id === value.clientId) ?? null;
  const q = search.trim().toLowerCase();
  const matches = (clients ?? [])
    .filter((c) => !q || c.name.toLowerCase().includes(q))
    .slice(0, MAX_SHOWN);
  const exact = (clients ?? []).some((c) => c.name.toLowerCase() === q);

  if (failed)
    return <Body muted>The list of clients could not be loaded. You can still make the trip.</Body>;
  if (value.newName !== null)
    return (
      <View style={{ gap: 8 }}>
        <Body>New client: {value.newName}</Body>
        <Body muted>The office will be asked to check it.</Body>
        <Button
          label="Choose a different client"
          kind="secondary"
          onPress={() => onChange(noClient)}
        />
      </View>
    );
  if (picked)
    return (
      <View style={{ gap: 8 }}>
        <Body>Delivering for {picked.name}</Body>
        {picked.sites.length > 0 && (
          <>
            <Body muted>Where at {picked.name}?</Body>
            {picked.sites.map((s) => (
              <Button
                key={s.id}
                label={s.status === "unconfirmed" ? `${s.name} (saved by a driver)` : s.name}
                kind={value.siteId === s.id ? "primary" : "secondary"}
                onPress={() => onChange({ ...value, siteId: value.siteId === s.id ? null : s.id })}
              />
            ))}
            <Body muted>A new place is saved when you deliver.</Body>
          </>
        )}
        <Button
          label="Choose a different client"
          kind="secondary"
          onPress={() => onChange(noClient)}
        />
      </View>
    );
  return (
    <View style={{ gap: 8 }}>
      <Input
        label="Who is it for? (optional)"
        value={search}
        onChangeText={setSearch}
        placeholder="Search your clients"
      />
      {clients === null && <Body muted>Loading clients...</Body>}
      {matches.map((c) => (
        <Button
          key={c.id}
          label={c.needs_review ? `${c.name} (new)` : c.name}
          kind="secondary"
          onPress={() => onChange({ clientId: c.id, siteId: null, newName: null })}
        />
      ))}
      {q.length >= 2 && !exact && (
        <Button
          label={`Add "${search.trim()}" as a new client`}
          kind="secondary"
          onPress={() => onChange({ clientId: null, siteId: null, newName: search.trim() })}
        />
      )}
    </View>
  );
}
