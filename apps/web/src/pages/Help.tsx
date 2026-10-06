import { ChevronRight, Mail, MessageCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { helpArticles } from "./helpArticles";
import PublicShell from "./PublicShell";

interface Contact {
  whatsapp: string | null;
  whatsapp_link: string | null;
  email: string | null;
  hours: string;
}

function ContactCard() {
  const [c, setC] = useState<Contact | null>(null);
  useEffect(() => {
    api
      .contact()
      .then(setC)
      .catch(() => setC(null));
  }, []);
  return (
    <div className="card">
      <h3>Still need help?</h3>
      {c && (c.whatsapp_link || c.email) ? (
        <>
          <p className="actions">
            {c.whatsapp_link && (
              <a className="btn" href={c.whatsapp_link} target="_blank" rel="noreferrer">
                <MessageCircle size={16} /> WhatsApp {c.whatsapp}
              </a>
            )}
            {c.email && (
              <a className="btn" href={`mailto:${c.email}`}>
                <Mail size={16} /> {c.email}
              </a>
            )}
          </p>
          <p className="muted">
            {c.hours}. Tell us your business name and what you see. Never send a password or a code.
          </p>
        </>
      ) : (
        <p className="muted">Support contact details will be shown here.</p>
      )}
    </div>
  );
}

/** Help articles, open to everyone (including people who cannot sign in), with a way to reach us. */
export default function Help() {
  const { slug } = useParams();
  const [query, setQuery] = useState("");
  const article = helpArticles.find((a) => a.slug === slug);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? helpArticles.filter((a) =>
          `${a.title} ${a.summary} ${a.body.join(" ")}`.toLowerCase().includes(q),
        )
      : helpArticles;
  }, [query]);
  return (
    <PublicShell
      title={article ? article.title : "How can we help?"}
      intro={article ? undefined : "Short guides for owners, office staff and drivers."}
      crumbs={
        article ? [{ label: "Help", to: "/help" }, { label: article.title }] : [{ label: "Help" }]
      }
    >
      {article ? (
        <>
          <div className="lp-article">
            {article.body.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </div>
          <p>
            <Link to="/help">All help articles</Link>
          </p>
        </>
      ) : (
        <>
          <input
            aria-label="Search the help pages"
            placeholder="Search, for example fuel or M-Pesa"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {shown.length === 0 && (
            <p className="muted">Nothing matches that. Try another word, or contact us below.</p>
          )}
          <ul className="lp-articles">
            {shown.map((a) => (
              <li key={a.slug}>
                <Link to={`/help/${a.slug}`}>
                  <strong>{a.title}</strong>
                  <span>{a.summary}</span>
                </Link>
                <ChevronRight size={18} aria-hidden="true" />
              </li>
            ))}
          </ul>
        </>
      )}
      <ContactCard />
    </PublicShell>
  );
}
