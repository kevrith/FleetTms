import type { Me } from "@fleettms/types";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, hasStoredTokens, onSignedOut } from "./api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  reload: () => Promise<Me | null>;
  signOut: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const next = await api.me();
      setMe(next);
      return next;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    onSignedOut(() => setMe(null));
    (async () => {
      if (await hasStoredTokens()) await reload();
      setLoading(false);
    })();
  }, [reload]);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* the token store is cleared either way */
    }
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ me, loading, reload, signOut, can: (p) => me?.permissions.includes(p) ?? false }),
    [me, loading, reload, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
