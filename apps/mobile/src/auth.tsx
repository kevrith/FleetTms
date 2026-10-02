import { availableViews, defaultView, type HomeView } from "@fleettms/business-rules";
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
  /** Owner-driver mode: which home the person is looking at. */
  views: HomeView[];
  view: HomeView;
  setView: (v: HomeView) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [chosenView, setChosenView] = useState<HomeView | null>(null);

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
      /* tokens are cleared either way */
    }
    setMe(null);
    setChosenView(null);
  }, []);

  const value = useMemo<AuthState>(() => {
    const roles = me?.roles ?? [];
    const views = availableViews(roles);
    const view = chosenView && views.includes(chosenView) ? chosenView : defaultView(roles);
    return { me, loading, reload, signOut, views, view, setView: setChosenView };
  }, [me, loading, reload, signOut, chosenView]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
