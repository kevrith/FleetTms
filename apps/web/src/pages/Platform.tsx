import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../auth";
import Admins from "../platform/Admins";
import Analytics from "../platform/Analytics";
import AuditLog from "../platform/AuditLog";
import CustomerDetail from "../platform/CustomerDetail";
import Customers from "../platform/Customers";
import Dashboard from "../platform/Dashboard";
import Feedback from "../platform/Feedback";
import Invoices from "../platform/Invoices";
import KraInvoices from "../platform/KraInvoices";
import PlatformShell from "../platform/PlatformShell";
import Renewals from "../platform/Renewals";
import SmsInbox from "../platform/SmsInbox";
import System from "../platform/System";
import Breaches from "./Breaches";
import Partners from "./Partners";
import UsageReport from "./UsageReport";

/** The Platform Admin console, for the people who run FleetTms itself. It has its own frame, apart from the business app. */
export default function Platform() {
  const { me } = useAuth();
  if (!me?.is_platform_admin) return <Navigate to="/" replace />;
  return (
    <PlatformShell>
      <Routes>
        <Route index element={<Dashboard />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="customers" element={<Customers />} />
        <Route path="customers/:id" element={<CustomerDetail />} />
        <Route path="renewals" element={<Renewals />} />
        <Route path="invoices" element={<Invoices />} />
        <Route path="partners" element={<Partners />} />
        <Route path="kra" element={<KraInvoices />} />
        <Route path="system" element={<System />} />
        <Route path="sms" element={<SmsInbox />} />
        <Route path="feedback" element={<Feedback />} />
        <Route path="usage" element={<UsageReport />} />
        <Route path="breaches" element={<Breaches />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="admins" element={<Admins />} />
        <Route path="*" element={<Navigate to="/platform" replace />} />
      </Routes>
    </PlatformShell>
  );
}
