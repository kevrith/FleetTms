import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface GoogleIdentity {
  accounts: {
    id: {
      initialize: (options: {
        client_id: string;
        callback: (r: { credential: string }) => void;
      }) => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}

const SCRIPT = "https://accounts.google.com/gsi/client";
let loading: Promise<void> | null = null;

function loadGoogle(): Promise<void> {
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loading = null;
      reject(new Error("Google could not be reached."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/** Google's own button, shown only when the API says Google sign-in is switched on. The page decides what to do with the token it returns. */
export default function GoogleButton({
  mode,
  onCredential,
}: {
  mode: "signin" | "signup";
  onCredential: (credential: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const latest = useRef(onCredential);
  latest.current = onCredential;
  const [clientId, setClientId] = useState<string | null>(null);

  useEffect(() => {
    api
      .authProviders()
      .then((p) => setClientId(p.google_client_id))
      .catch(() => setClientId(null));
  }, []);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    loadGoogle()
      .then(() => {
        const google = (window as unknown as { google?: GoogleIdentity }).google;
        if (cancelled || !google || !holder.current) return;
        google.accounts.id.initialize({
          client_id: clientId,
          callback: (r) => latest.current(r.credential),
        });
        google.accounts.id.renderButton(holder.current, {
          theme: "outline",
          size: "large",
          text: mode === "signup" ? "signup_with" : "signin_with",
          shape: "rectangular",
          width: Math.min(Math.max(holder.current.clientWidth, 200), 400),
        });
      })
      .catch(() => {
        /* the form still works without it */
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, mode]);

  if (!clientId) return null;
  return (
    <>
      <p className="auth-divider">or</p>
      <div ref={holder} className="google-button" />
    </>
  );
}
