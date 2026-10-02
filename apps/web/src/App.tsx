import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { HealthResponse } from "@fleettms/types";
import { api } from "./api";
import { useAuth } from "./auth";
import Layout from "./Layout";
import { navItems } from "./nav";
import ExpiringDocuments from "./pages/ExpiringDocuments";
import AcceptInvite from "./pages/AcceptInvite";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Expenses from "./pages/Expenses";
import Reports from "./pages/Reports";
import Clients from "./pages/Clients";
import Incidents from "./pages/Incidents";
import Jobs from "./pages/Jobs";
import Workshop from "./pages/Workshop";
import Settings from "./pages/Settings";
import StaffArea from "./pages/Payroll";
import Leases from "./pages/Leases";
import Portal from "./pages/Portal";
import Suppliers from "./pages/Suppliers";
import TripDetail from "./pages/TripDetail";
import Trips from "./pages/Trips";
import VehicleDetail from "./pages/VehicleDetail";
import Vehicles from "./pages/Vehicles";
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

  if (me?.permissions.includes("lease.view_own") && !me.permissions.includes("vehicles.view")) {
    return <Navigate to="/portal" replace />;
  }
  const dashboard = [
    "finance.view",
    "vehicles.view",
    "expenses.view",
    "reconciliations.approve",
  ].some((p) => me?.permissions.includes(p));
  return (
    <>
      <h2>How is my business doing right now?</h2>
      <p>Welcome, {me?.user.name}.</p>
      {dashboard ? <Dashboard /> : <ExpiringDocuments />}
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
        <Route path="/vehicles" element={<Vehicles />} />
        <Route path="/vehicles/:id" element={<VehicleDetail />} />
        <Route path="/expenses/*" element={<Expenses />} />
        <Route path="/trips" element={<Trips />} />
        <Route path="/workshop/*" element={<Workshop />} />
        <Route path="/incidents/*" element={<Incidents />} />
        <Route path="/jobs/*" element={<Jobs />} />
        <Route path="/clients/*" element={<Clients />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/trips/:id" element={<TripDetail />} />
        <Route path="/staff/*" element={<StaffArea />} />
        <Route path="/leases/*" element={<Leases />} />
        <Route path="/suppliers/*" element={<Suppliers />} />
        <Route path="/portal" element={<Portal />} />
        <Route path="/settings/*" element={<Settings />} />
        <Route path="*" element={<Placeholder />} />
      </Route>
    </Routes>
  );
}
