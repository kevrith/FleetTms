import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import "./landing.css";

export function PublicHeader() {
  return (
    <header className="lp-bar">
      <div className="lp-wrap lp-bar-row">
        <Link to="/" className="lp-brand">
          <img src="/logo.png" alt="" width={36} height={36} />
          FleetTms
        </Link>
        <nav className="lp-links" aria-label="Main">
          <a href="/#features">Features</a>
          <a href="/#how">How it works</a>
          <a href="/#pricing">Pricing</a>
          <Link to="/partners">Partners</Link>
          <Link to="/help">Help</Link>
        </nav>
        <div className="lp-bar-actions">
          <Link className="lp-btn lp-btn-ghost lp-signin" to="/login">
            Sign in
          </Link>
          <Link className="lp-btn lp-btn-primary" to="/signup">
            Start free trial
          </Link>
        </div>
      </div>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="lp-foot">
      <div className="lp-wrap lp-foot-row">
        <div>
          <span className="lp-brand lp-brand-foot">
            <img src="/logo.png" alt="" width={28} height={28} />
            FleetTms
          </span>
          <p>Fleet management for Kenyan transport businesses.</p>
        </div>
        <nav aria-label="Footer">
          <a href="/#features">Features</a>
          <a href="/#pricing">Pricing</a>
          <Link to="/partners">Partners</Link>
          <Link to="/help">Help and contact</Link>
          <Link to="/login">Sign in</Link>
        </nav>
      </div>
      <div className="lp-wrap lp-legal">Kastra Enterprises</div>
    </footer>
  );
}

/**
 * The frame for every page a visitor can open without signing in: the same header and footer as
 * the front page. "form" centres a single card (sign in, sign up); "page" is a readable column.
 */
export default function PublicShell({
  children,
  layout = "page",
  title,
  intro,
  crumbs,
}: {
  children: ReactNode;
  layout?: "page" | "form";
  title?: string;
  intro?: string;
  crumbs?: { label: string; to?: string }[];
}) {
  return (
    <div className="lp lp-shell">
      <PublicHeader />
      {layout === "page" && (title || crumbs) && (
        <section className="lp-pagehead">
          <div className="lp-wrap lp-narrow">
            {crumbs && (
              <nav className="lp-crumbs" aria-label="Breadcrumb">
                <Link to="/">Home</Link>
                {crumbs.map((c) => (
                  <span key={c.label}>
                    <span aria-hidden="true"> / </span>
                    {c.to ? <Link to={c.to}>{c.label}</Link> : c.label}
                  </span>
                ))}
              </nav>
            )}
            {title && <h1>{title}</h1>}
            {intro && <p>{intro}</p>}
          </div>
        </section>
      )}
      <main className={layout === "form" ? "lp-formpage" : "lp-page"}>
        <div className={layout === "form" ? "lp-formwrap" : "lp-wrap lp-narrow"}>{children}</div>
      </main>
      <PublicFooter />
    </div>
  );
}
