import type { Trip } from "@fleettms/types";
import { useState } from "react";
import { View } from "react-native";
import type { SiteToSave } from "../offline/runtime";
import { Body, Button, Input } from "../ui";

/**
 * Asked at delivery when the trip is for a client and nobody knows where that client takes deliveries: "save this place so the next
 * driver is guided here". What a driver saves waits for the office to confirm; until then it guides and is not held against anyone.
 */
export function useSaveSite(trip: Trip | null | undefined) {
  const offered = !!trip?.client && !trip.site;
  const [save, setSave] = useState(true);
  const [name, setName] = useState(trip?.destination ?? "");
  return {
    offered,
    save,
    setSave,
    name,
    setName,
    // A name is needed only when the place is going to be saved.
    valid: !offered || !save || name.trim().length >= 2,
  };
}
export type SaveSiteState = ReturnType<typeof useSaveSite>;

/** The place to send with the delivery, or null when nothing is to be saved. */
export function siteToSave(
  state: SaveSiteState,
  where: { lat: number; lng: number } | null,
): SiteToSave | null {
  if (!state.offered || !state.save || state.name.trim().length < 2) return null;
  return { name: state.name.trim(), lat: where?.lat ?? null, lng: where?.lng ?? null };
}

export function SaveSiteChoice({
  trip,
  state,
}: {
  trip: Trip | null | undefined;
  state: SaveSiteState;
}) {
  if (!state.offered || !trip?.client) return null;
  return (
    <View style={{ gap: 8 }}>
      <Body muted>
        {trip.client.name} has no delivery place saved yet. Save where you are now, so the next
        driver is guided here.
      </Body>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Button
            label="Save this place"
            kind={state.save ? "primary" : "secondary"}
            onPress={() => state.setSave(true)}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            label="Do not save"
            kind={state.save ? "secondary" : "primary"}
            onPress={() => state.setSave(false)}
          />
        </View>
      </View>
      {state.save && (
        <Input
          label="What do you call this place?"
          value={state.name}
          onChangeText={state.setName}
          placeholder="Main yard, Ruiru depot"
        />
      )}
    </View>
  );
}
