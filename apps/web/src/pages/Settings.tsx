import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../auth";
import Audit from "./Audit";
import Checklist from "./Checklist";
import Depots from "./Depots";
import ImportData from "./ImportData";
import PaymentSettingsPage from "./PaymentSettings";
import Security from "./Security";
import Users from "./Users";

export default function Settings() {
  const { can } = useAuth();
  const tabs = [
    { to: "people", label: "People", show: can("users.view") },
    { to: "depots", label: "Depots", show: can("depots.view") },
    { to: "checklist", label: "Inspection checklist", show: can("vehicles.manage") },
    {
      to: "payments",
      label: "Payments and tax",
      show: can("business.manage") || can("invoices.manage"),
    },
    { to: "import", label: "Import from Excel", show: can("data.import") },
    { to: "audit", label: "Audit trail", show: can("audit.view") },
    { to: "security", label: "Security", show: true },
  ].filter((t) => t.show);

  return (
    <>
      <h2>Settings</h2>
      <nav className="tabs">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to={tabs[0]?.to ?? "security"} replace />} />
        {can("users.view") && <Route path="people" element={<Users />} />}
        {can("depots.view") && <Route path="depots" element={<Depots />} />}
        {can("vehicles.manage") && <Route path="checklist" element={<Checklist />} />}
        {(can("business.manage") || can("invoices.manage")) && (
          <Route path="payments" element={<PaymentSettingsPage />} />
        )}
        {can("data.import") && <Route path="import" element={<ImportData />} />}
        {can("audit.view") && <Route path="audit" element={<Audit />} />}
        <Route path="security" element={<Security />} />
        <Route path="*" element={<Navigate to="." replace />} />
      </Routes>
    </>
  );
}
