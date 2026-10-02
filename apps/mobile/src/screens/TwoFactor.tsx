import { useState } from "react";
import { ScrollView, Text } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Button, ErrorText, errorMessage, Input, Screen, Title, useTheme } from "../ui";

export default function TwoFactorScreen() {
  const { reload, signOut } = useAuth();
  const theme = useTheme();
  const { me } = useAuth();
  const [method, setMethod] = useState<null | "totp" | "sms">(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function choose(next: "totp" | "sms") {
    setError(null);
    setCode("");
    try {
      if (next === "totp") setSecret((await api.twoFactorSetup()).secret);
      else await api.smsTwoFactorSetup();
      setMethod(next);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function confirm() {
    setError(null);
    try {
      if (method === "sms") await api.smsTwoFactorConfirm(code);
      else await api.twoFactorConfirm(code);
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ gap: 16, flexGrow: 1, justifyContent: "center" }}
        keyboardShouldPersistTaps="handled"
      >
        <Title>Set up two-step verification</Title>
        {method === null && (
          <>
            <Body>Choose how you want to receive your sign-in codes.</Body>
            <Button label="Authenticator app" onPress={() => choose("totp")} />
            <Button
              label="Text message"
              kind="secondary"
              onPress={() => choose("sms")}
              disabled={!me?.user.phone}
            />
            {!me?.user.phone && (
              <Body muted>Text messages need a phone number on your account.</Body>
            )}
          </>
        )}
        {method === "totp" && (
          <Body>
            Open an authenticator app (Google Authenticator, Authy), choose "enter a setup key", and
            type in this key. You can also scan the QR code on the web dashboard.
          </Body>
        )}
        {method === "totp" && secret && (
          <Text selectable style={{ color: theme.text, fontSize: 20, fontFamily: "monospace" }}>
            {secret}
          </Text>
        )}
        {method === "sms" && <Body>We texted a 6-digit code to your phone.</Body>}
        {method !== null && (
          <Input
            label="6-digit code"
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            maxLength={6}
          />
        )}
        <ErrorText message={error} />
        {method !== null && (
          <Button label="Turn on" onPress={confirm} disabled={code.length !== 6} />
        )}
        <Button label="Sign out" kind="secondary" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}
