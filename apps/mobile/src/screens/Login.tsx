import { ApiError } from "@fleettms/api-client";
import { useEffect, useState } from "react";
import { ScrollView } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { clearQuick, getQuick, type QuickCredentials } from "../quick";
import { Body, Button, ErrorText, errorMessage, Input, Screen, Title } from "../ui";

type Mode = "driver" | "staff";

/** Quick sign-in: the PIN, on a phone that was already signed in with an SMS code and turned this on. */
function PinLogin({
  creds,
  onFallback,
}: {
  creds: QuickCredentials;
  onFallback: (notice?: string) => void;
}) {
  const { reload } = useAuth();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.quickLogin({
        phone: creds.phone,
        device_id: creds.deviceId,
        device_secret: creds.secret,
        pin,
        device_label: "FleetTms mobile",
      });
      await reload();
    } catch (e) {
      if (
        e instanceof ApiError &&
        (e.code === "quick_login_locked" || e.code === "invalid_credentials")
      ) {
        // Quick sign-in is no longer valid for this phone: forget it and use an SMS code.
        await clearQuick();
        onFallback(
          e.code === "quick_login_locked"
            ? "Too many wrong PINs, so quick sign-in was switched off. Sign in with an SMS code."
            : "Quick sign-in is no longer on for this phone. Sign in with an SMS code.",
        );
      } else {
        setError(errorMessage(e));
        setPin("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Body>Welcome back. Enter your PIN.</Body>
      <Body muted>{creds.phone}</Body>
      <Input
        label="6-digit PIN"
        value={pin}
        onChangeText={(v) => setPin(v.replace(/\D/g, ""))}
        keyboardType="number-pad"
        secureTextEntry
        maxLength={6}
        autoFocus
      />
      <ErrorText message={error} />
      <Button label="Sign in" onPress={submit} busy={busy} disabled={pin.length !== 6} />
      <Button
        label="Use an SMS code instead"
        kind="secondary"
        onPress={() => onFallback()}
        disabled={busy}
      />
    </>
  );
}

/** The first sign-in on a phone always uses an SMS code. After quick sign-in is turned on, a PIN is offered instead. */
function DriverSignIn() {
  const [creds, setCreds] = useState<QuickCredentials | null | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void getQuick().then(setCreds);
  }, []);

  if (creds === undefined) return null;
  if (creds) {
    return (
      <PinLogin
        creds={creds}
        onFallback={(message) => {
          setNotice(message ?? null);
          setCreds(null);
        }}
      />
    );
  }
  return (
    <>
      {notice && <Body muted>{notice}</Body>}
      <DriverLogin />
    </>
  );
}

function DriverLogin() {
  const { reload } = useAuth();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function sendCode() {
    setBusy(true);
    setError(null);
    try {
      await api.otpRequest(phone);
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      await api.otpVerify({ phone, code, device_label: "FleetTms mobile" });
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Input
        label="Phone number"
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        placeholder="0712 345 678"
        editable={!sent}
      />
      {sent && (
        <>
          <Body muted>We sent a 6-digit code by SMS. It works for 5 minutes.</Body>
          <Input
            label="6-digit code"
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            maxLength={6}
            autoFocus
          />
        </>
      )}
      <ErrorText message={error} />
      {sent ? (
        <>
          <Button label="Sign in" onPress={verify} busy={busy} disabled={code.length !== 6} />
          <Button label="Send a new code" kind="secondary" onPress={sendCode} disabled={busy} />
        </>
      ) : (
        <Button
          label="Send me a code"
          onPress={sendCode}
          busy={busy}
          disabled={phone.trim().length < 9}
        />
      )}
    </>
  );
}

function StaffLogin() {
  const { reload } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [step, setStep] = useState<null | "totp" | "sms">(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.login({
        identifier,
        password,
        totp_code: step === "totp" ? totp : undefined,
        sms_code: step === "sms" ? totp : undefined,
        device_label: "FleetTms mobile",
      });
      await reload();
    } catch (e) {
      if (e instanceof ApiError && e.code === "two_factor_required") setStep("totp");
      else if (e instanceof ApiError && e.code === "sms_code_required") {
        setStep("sms");
        setTotp("");
        setError(e.message);
      } else setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Input
        label="Email or phone number"
        value={identifier}
        onChangeText={setIdentifier}
        autoCapitalize="none"
        keyboardType="email-address"
      />
      <Input
        label="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoCapitalize="none"
      />
      {step && (
        <Input
          label={step === "sms" ? "Code we texted you" : "Code from your authenticator app"}
          value={totp}
          onChangeText={setTotp}
          keyboardType="number-pad"
          maxLength={6}
          autoFocus
        />
      )}
      <ErrorText message={error} />
      <Button
        label={step ? "Verify and sign in" : "Sign in"}
        onPress={submit}
        busy={busy}
        disabled={!identifier || !password}
      />
    </>
  );
}

export default function LoginScreen() {
  const [mode, setMode] = useState<Mode>("driver");
  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ gap: 16, flexGrow: 1, justifyContent: "center" }}
        keyboardShouldPersistTaps="handled"
      >
        <Title>FleetTms</Title>
        <Body muted>{mode === "driver" ? "Driver sign in" : "Owner and staff sign in"}</Body>
        {mode === "driver" ? <DriverSignIn /> : <StaffLogin />}
        <Button
          kind="secondary"
          label={mode === "driver" ? "I am an owner or office staff" : "I am a driver or turnboy"}
          onPress={() => setMode(mode === "driver" ? "staff" : "driver")}
        />
      </ScrollView>
    </Screen>
  );
}
