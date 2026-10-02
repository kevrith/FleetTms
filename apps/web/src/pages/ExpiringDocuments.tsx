import type { ComplianceDocument, StaffProfile, Vehicle } from "@fleettms/types";
import { FileWarning } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { DOC_TYPE } from "../labels";
import { Card } from "../ui";
import { ExpiryBadge } from "./DocumentsPanel";

/** Home card: documents that have expired or expire within 30 days. Hidden when there is nothing to show. */
export default function ExpiringDocuments() {
  const { can } = useAuth();
  const [docs, setDocs] = useState<ComplianceDocument[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const allowed = can("vehicles.view") || can("staff.view");

  useEffect(() => {
    if (!allowed) return;
    api
      .expiringDocuments(30)
      .then(setDocs)
      .catch(() => setDocs([]));
    if (can("vehicles.view"))
      api
        .vehicles()
        .then(setVehicles)
        .catch(() => undefined);
    if (can("staff.view"))
      api
        .staff()
        .then(setStaff)
        .catch(() => undefined);
  }, [allowed, can]);

  if (docs.length === 0) return null;
  const subject = (d: ComplianceDocument) =>
    d.vehicle_id
      ? (vehicles.find((v) => v.id === d.vehicle_id)?.registration ?? "Vehicle")
      : (staff.find((s) => s.membership_id === d.membership_id)?.name ?? "Staff member");

  return (
    <Card title="Documents needing attention">
      <ul className="list">
        {docs.map((d) => (
          <li key={d.id}>
            <span>
              <FileWarning size={16} />{" "}
              <Link to={d.vehicle_id ? `/vehicles/${d.vehicle_id}` : "/staff"}>{subject(d)}</Link>{" "}
              <span className="muted">{DOC_TYPE[d.doc_type]}</span>
            </span>
            <ExpiryBadge iso={d.expires_on} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
