import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { clearQuick, deviceId, getQuick, saveQuick } from "../quick";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

/**
 * Settings for signing in with a PIN instead of an SMS code. The first sign-in on a phone always uses the SMS code;
 * this only turns on a faster way back in on this phone, and a lost phone can still be cut off by signing out everywhere.
 */
export function QuickSignInCard() {
  const t = useTheme();
  const { me } = useAuth();
  const [on, setOn] = useState<boolean | null>(null);
  const [editing, setEditing] = useState(false);
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const creds = await getQuick();
      setOn(creds ? (await api.quickLoginStatus(creds.deviceId)).enabled : false);
    } catch {
      setOn(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // Only drivers and turnboys use the SMS-code sign-in this replaces.
  const eligible =
    me?.roles.every((r) => r === "driver" || r === "turnboy") && Boolean(me?.user.phone);
  if (!eligible || on === null) return null;

  async function turnOn() {
    setBusy(true);
    setError(null);
    try {
      const id = await deviceId();
      const { device_secret } = await api.quickLoginEnable({
        device_id: id,
        pin,
        device_label: "FleetTms mobile",
      });
      await saveQuick({ phone: me?.user.phone ?? "", deviceId: id, secret: device_secret });
      setEditing(false);
      setPin("");
      setAgain("");
      setOn(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    setError(null);
    try {
      await api.quickLoginDisable(await deviceId());
      await clearQuick();
      setOn(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}>
      <Body>Quick sign-in on this phone: {on ? "On" : "Off"}</Body>
      <Body muted>
        {on
          ? "You sign in with your 6-digit PIN instead of an SMS code."
          : "Sign in with a 6-digit PIN instead of an SMS code. Only turn this on for your own phone."}
      </Body>
      <ErrorText message={error} />
      {editing ? (
        <>
          <Input
            label="Choose a 6-digit PIN"
            value={pin}
            onChangeText={(v) => setPin(v.replace(/\D/g, ""))}
            keyboardType="number-pad"
            secureTextEntry
            maxLength={6}
          />
          <Input
            label="Type it again"
            value={again}
            onChangeText={(v) => setAgain(v.replace(/\D/g, ""))}
            keyboardType="number-pad"
            secureTextEntry
            maxLength={6}
          />
          {pin.length === 6 && again.length === 6 && pin !== again && (
            <Body muted>The two PINs are different.</Body>
          )}
          <Button
            label={on ? "Save new PIN" : "Turn on quick sign-in"}
            onPress={turnOn}
            busy={busy}
            disabled={pin.length !== 6 || pin !== again}
          />
          <Button
            label="Cancel"
            kind="secondary"
            onPress={() => {
              setEditing(false);
              setPin("");
              setAgain("");
              setError(null);
            }}
            disabled={busy}
          />
        </>
      ) : on ? (
        <>
          <Button label="Change PIN" kind="secondary" onPress={() => setEditing(true)} />
          <Button label="Turn off" kind="secondary" onPress={turnOff} busy={busy} />
        </>
      ) : (
        <Button label="Turn on quick sign-in" kind="secondary" onPress={() => setEditing(true)} />
      )}
    </View>
  );
}
