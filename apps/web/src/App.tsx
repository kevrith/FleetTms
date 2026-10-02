import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { HealthResponse } from "@fleettms/types";
import { api } from "./api";
import { useAuth } from "./auth";
import Layout from "./Layout";
import { navItems } from "./nav";
import AcceptInvite from "./pages/AcceptInvite";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Signup from "./pages/Signup";
import TwoFactor from "./pages/TwoFactor";

function Home() {
  const { me } = useAuth();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setFailed(true));
  }, []);

  return (
    <>
      <h2>How is my business doing right now?</h2>
      <p>
        Welcome, {me?.user.name}. Your dashboard fills up as vehicles, trips and expenses are added.
      </p>
      {health && (
        <p className="status ok">
          <CheckCircle2 size={18} /> Connected to FleetTms API (v{health.version})
        </p>
      )}
      {failed && (
        <p className="status bad">
          <XCircle size={18} /> Cannot reach the FleetTms API. Check that it is running.
        </p>
      )}
    </>
  );
}

function Placeholder() {
  const { pathname } = useLocation();
  const item = navItems.find((n) => n.path === pathname);
  return <h2>{item?.label ?? "Page not found"} (coming soon)</h2>;
}

/** Sends signed-out visitors to sign-in, and people who still owe two-step setup to that screen. */
function RequireAuth({ children }: { children: JSX.Element }) {
  const { me, loading } = useAuth();
  const { pathname } = useLocation();
  if (loading) return <p className="main">Loading...</p>;
  if (!me) return <Navigate to="/login" replace />;
  if (me.mfa_setup_required && pathname !== "/two-factor")
    return <Navigate to="/two-factor" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/accept-invite" element={<AcceptInvite />} />
      <Route
        path="/two-factor"
        element={
          <RequireAuth>
            <TwoFactor />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/settings/*" element={<Settings />} />
        <Route path="*" element={<Placeholder />} />
      </Route>
    </Routes>
  );
}
