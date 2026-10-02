import type { ImportResult } from "@fleettms/types";
import { Download, Upload } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage } from "../ui";

type Kind = "vehicles" | "staff";

function ImportCard({ kind, title, help }: { kind: Kind; title: string; help: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function template() {
    try {
      const blob = await api.importTemplate(kind);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fleettms-${kind}-template.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.importFile(kind, file, dryRun));
    } catch (e) {
      setResult(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={title}>
      <p className="muted">{help}</p>
      <ErrorBanner message={error} />
      <p>
        <button className="btn" onClick={template}>
          <Download size={16} /> Download template
        </button>
      </p>
      <p>
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setResult(null);
          }}
        />
      </p>
      <p className="actions">
        <button className="btn" disabled={!file || busy} onClick={() => run(true)}>
          Check file
        </button>
        <button className="btn primary" disabled={!file || busy} onClick={() => run(false)}>
          <Upload size={16} /> Import
        </button>
      </p>
      {result && result.errors.length === 0 && (
        <p className="status ok">
          {result.dry_run
            ? `${result.rows} rows look good. Nothing was imported yet.`
            : `Imported ${result.imported} rows.`}
        </p>
      )}
      {result && result.errors.length > 0 && (
        <>
          <p className="status bad">Nothing was imported. Fix these rows and upload again.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Column</th>
                  <th>Problem</th>
                </tr>
              </thead>
              <tbody>
                {result.errors.map((er, i) => (
                  <tr key={i}>
                    <td>{er.row}</td>
                    <td>{er.column ?? ""}</td>
                    <td>{er.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {result && result.invite_tokens.length > 0 && (
        <>
          <p>
            Invite codes for people who sign in with a password. Share each one privately; they are
            shown once.
          </p>
          <ul className="list">
            {result.invite_tokens.map((t) => (
              <li key={t.row}>
                <span>{t.name}</span>
                <code>{t.invite_token}</code>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

export default function ImportData() {
  return (
    <>
      <ImportCard
        kind="vehicles"
        title="Import vehicles"
        help="One row per vehicle. For leased or financed vehicles, put the lessor, lender or lessee name in the last-but-two column. If any row has a problem, nothing is imported."
      />
      <ImportCard
        kind="staff"
        title="Import staff"
        help="One row per person. Drivers and turnboys need a phone number; other roles need an email. Roles can be separated by commas."
      />
    </>
  );
}
