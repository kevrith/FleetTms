import { useEffect, useState } from "react";
import { ScrollView, Text } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Button, ErrorText, errorMessage, Input, Screen, Title, useTheme } from "../ui";

export default function TwoFactorScreen() {
  const { reload, signOut } = useAuth();
  const theme = useTheme();
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .twoFactorSetup()
      .then((s) => setSecret(s.secret))
      .catch((e) => setError(errorMessage(e)));
  }, []);

  async function confirm() {
    setError(null);
    try {
      await api.twoFactorConfirm(code);
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
        <Body>
          Open an authenticator app (Google Authenticator, Authy), choose "enter a setup key", and
          type in this key. You can also scan the QR code on the web dashboard.
        </Body>
        {secret && (
          <Text selectable style={{ color: theme.text, fontSize: 20, fontFamily: "monospace" }}>
            {secret}
          </Text>
        )}
        <Input
          label="6-digit code"
          value={code}
          onChangeText={setCode}
          keyboardType="number-pad"
          maxLength={6}
        />
        <ErrorText message={error} />
        <Button label="Turn on" onPress={confirm} disabled={code.length !== 6} />
        <Button label="Sign out" kind="secondary" onPress={signOut} />
      </ScrollView>
    </Screen>
  );
}
