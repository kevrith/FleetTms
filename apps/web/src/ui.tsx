import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="banner bad" role="alert">
      <AlertTriangle size={18} /> {message}
    </p>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title && <h3>{title}</h3>}
      {children}
    </section>
  );
}
