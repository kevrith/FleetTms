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
import { ApiError } from "@fleettms/api-client";
import * as SecureStore from "expo-secure-store";
import { api, hasStoredTokens, onSignedOut } from "./api";

const ME_KEY = "fleettms.me";

// The last signed-in identity, kept in the secure keystore so the app opens with no network.
// Only the fields the app uses; cleared when the person signs out or the server ends the session.
async function saveMe(me: Me): Promise<void> {
  try {
    await SecureStore.setItemAsync(
      ME_KEY,
      JSON.stringify({ ...me, companies: [], pending_documents: [] }),
    );
  } catch {
    /* the next open will need a connection */
  }
}
async function loadMe(): Promise<Me | null> {
  try {
    const raw = await SecureStore.getItemAsync(ME_KEY);
    return raw ? (JSON.parse(raw) as Me) : null;
  } catch {
    return null;
  }
}
async function forgetMe(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(ME_KEY);
  } catch {
    /* nothing to clear */
  }
}

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
      void saveMe(next);
      return next;
    } catch (e) {
      if (!(e instanceof ApiError) || e.status >= 500) {
        // No network or the server is down: carry on from the saved identity. The server decides again once it is reachable.
        const saved = await loadMe();
        if (saved) {
          setMe(saved);
          return saved;
        }
      } else {
        void forgetMe();
      }
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    onSignedOut(() => {
      setMe(null);
      void forgetMe();
    });
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
    void forgetMe();
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
