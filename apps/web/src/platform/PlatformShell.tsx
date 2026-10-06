import {
  Activity,
  BarChart3,
  CalendarClock,
  FileText,
  Gauge,
  Handshake,
  History,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Receipt,
  Search,
  ShieldAlert,
  ShieldCheck,
  Users,
  UserCog,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ToastProvider, useLoad } from "./kit";
import "./platform.css";

const GROUPS: {
  title: string;
  items: { to: string; label: string; icon: typeof Users; end?: boolean; badge?: string }[];
}[] = [
  {
    title: "Business",
    items: [
      { to: "/platform", label: "Overview", icon: LayoutDashboard, end: true },
      { to: "/platform/analytics", label: "Analytics", icon: BarChart3 },
      { to: "/platform/customers", label: "Customers", icon: Users },
      { to: "/platform/renewals", label: "Renewals", icon: CalendarClock, badge: "renewals" },
      { to: "/platform/invoices", label: "Invoices", icon: Receipt, badge: "invoices" },
      { to: "/platform/partners", label: "Partners", icon: Handshake },
    ],
  },
  {
    title: "Operations",
    items: [
      { to: "/platform/system", label: "System status", icon: Gauge },
      { to: "/platform/kra", label: "KRA invoices", icon: FileText, badge: "kra" },
      { to: "/platform/feedback", label: "Feedback", icon: MessageSquareText, badge: "feedback" },
      { to: "/platform/usage", label: "Product usage", icon: Activity },
    ],
  },
  {
    title: "Governance",
    items: [
      { to: "/platform/breaches", label: "Data breaches", icon: ShieldAlert, badge: "breaches" },
      { to: "/platform/audit", label: "Audit log", icon: History },
      { to: "/platform/admins", label: "Platform admins", icon: UserCog },
    ],
  },
];

/** Which attention items put a count next to which menu entry. */
const BADGES: Record<string, string[]> = {
  renewals: ["read_only", "grace", "trials_ending"],
  invoices: ["invoices_overdue"],
  kra: ["etims_review"],
  feedback: ["feedback_new"],
  breaches: ["breaches_overdue", "breaches_open"],
};

function Search_() {
  const nav = useNavigate();
  const [query, setQuery] = useState("");
  const [list, setList] = useState<{ id: string; name: string }[] | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);
  const found = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q && list ? list.filter((b) => b.name.toLowerCase().includes(q)).slice(0, 8) : [];
  }, [query, list]);
  return (
    <div className="pf-search" ref={box}>
      <Search size={16} />
      <input
        type="search"
        placeholder="Find a customer"
        aria-label="Find a customer"
        value={query}
        onFocus={() => {
          setOpen(true);
          if (!list)
            void api
              .platformBusinesses()
              .then((rows) => setList(rows.map((r) => ({ id: r.id, name: r.name }))))
              .catch(() => setList([]));
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && found[0]) {
            nav(`/platform/customers/${found[0].id}`);
            setOpen(false);
            setQuery("");
          }
        }}
      />
      {open && found.length > 0 && (
        <div className="pf-results" role="listbox">
          {found.map((b) => (
            <button
              key={b.id}
              role="option"
              aria-selected="false"
              onClick={() => {
                nav(`/platform/customers/${b.id}`);
                setOpen(false);
                setQuery("");
              }}
            >
              {b.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The console's own frame: a dark sidebar with counts that say what needs attention, a search for any customer, and the environment. */
export default function PlatformShell({ children }: { children: ReactNode }) {
  const { me, signOut } = useAuth();
  const attention = useLoad(() => api.platformAttention());
  const reloadAttention = attention.reload;
  const health = useLoad(() => api.platformHealth());
  useEffect(() => {
    const timer = setInterval(() => void reloadAttention(), 120_000);
    return () => clearInterval(timer);
  }, [reloadAttention]);
  const counts = (badge?: string) => {
    if (!badge) return 0;
    const keys = BADGES[badge] ?? [];
    return (attention.data ?? [])
      .filter((i) => keys.includes(i.key))
      .reduce((n, i) => n + i.count, 0);
  };
  const env = health.data?.environment;

  return (
    <ToastProvider>
      <div className="pf">
        <aside className="pf-side">
          <div className="pf-brand">
            <img className="pf-brand-mark" src="/logo.png" alt="" width={32} height={32} />
            <span>
              FleetTms
              <small>Platform console</small>
            </span>
          </div>
          <nav aria-label="Console">
            {GROUPS.map((g) => (
              <div key={g.title}>
                <div className="pf-group">{g.title}</div>
                {g.items.map(({ to, label, icon: Icon, end, badge }) => {
                  const n = counts(badge);
                  return (
                    <NavLink
                      key={to}
                      to={to}
                      end={end}
                      className={({ isActive }) => `pf-link${isActive ? " active" : ""}`}
                    >
                      <Icon size={17} /> {label}
                      {n > 0 && (
                        <span className="pf-count" aria-label={`${n} need attention`}>
                          {n}
                        </span>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="pf-side-foot">
            <strong>{me?.user.name}</strong>
            <span>Platform admin</span>
            {me?.business && (
              <Link className="pf-btn" to="/">
                <ShieldCheck size={15} /> Back to {me.business.name}
              </Link>
            )}
            <button className="pf-btn" onClick={() => void signOut()}>
              <LogOut size={15} /> Sign out
            </button>
          </div>
        </aside>
        <div className="pf-main">
          <header className="pf-top">
            <Search_ />
            {env && (
              <span className={`pf-env${env === "production" ? " live" : ""}`}>
                {env === "production" ? "LIVE" : env}
              </span>
            )}
          </header>
          <main className="pf-content">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
