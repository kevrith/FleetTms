import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Search, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../ui";

// ---- loading ------------------------------------------------------------------------------------------------------------------

/** Loads something when the page opens (and again when `deps` change); `reload()` asks again after a change. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loader = useRef(load);
  loader.current = load;
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loader.current());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void reload(), deps);
  return { data, error, loading, reload, setData };
}

// ---- toasts -------------------------------------------------------------------------------------------------------------------

interface ToastApi {
  ok: (message: string) => void;
  err: (message: string) => void;
}
const ToastContext = createContext<ToastApi>({ ok: () => undefined, err: () => undefined });
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; text: string; bad: boolean }[]>([]);
  const next = useRef(1);
  const push = useCallback((text: string, bad: boolean) => {
    const id = next.current++;
    setItems((all) => [...all, { id, text, bad }]);
    setTimeout(() => setItems((all) => all.filter((t) => t.id !== id)), bad ? 7000 : 4000);
  }, []);
  const api = useMemo(
    () => ({ ok: (m: string) => push(m, false), err: (m: string) => push(m, true) }),
    [push],
  );
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pf-toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`pf-toast${t.bad ? " err" : ""}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// ---- page furniture -----------------------------------------------------------------------------------------------------------

export function Page({
  title,
  subtitle,
  crumbs,
  actions,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  crumbs?: { to?: string; label: string }[];
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      {crumbs && (
        <nav className="pf-crumbs" aria-label="Breadcrumb">
          {crumbs.map((c, i) => (
            <span key={c.label}>
              {i > 0 && " / "}
              {c.to ? <Link to={c.to}>{c.label}</Link> : c.label}
            </span>
          ))}
        </nav>
      )}
      <div className="pf-head">
        <div>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {actions && <div className="pf-actions">{actions}</div>}
      </div>
      {children}
    </>
  );
}

export function Panel({
  title,
  actions,
  flush,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={`pf-panel${flush ? " flush" : ""}`}>
      {(title || actions) && (
        <header>
          {title && <h2>{title}</h2>}
          {actions && <div className="pf-actions">{actions}</div>}
        </header>
      )}
      <div className="pf-body">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "ok" | "warn" | "bad";
  icon?: ReactNode;
}) {
  return (
    <div className={`pf-stat${tone ? ` ${tone}` : ""}`}>
      <div className="label">
        {icon}
        {label}
      </div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Badge({
  tone,
  children,
}: {
  tone?: "ok" | "warn" | "bad" | "info" | "accent";
  children: ReactNode;
}) {
  return <span className={`pf-badge${tone ? ` ${tone}` : ""}`}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="pf-empty">{children}</div>;
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="pf-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          type="button"
        >
          {t.label}
          {t.count !== undefined ? ` (${t.count})` : ""}
        </button>
      ))}
    </div>
  );
}

export function Chips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="pf-chips">
      {options.map((o) => (
        <button
          key={o.id}
          className="pf-chip"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          type="button"
        >
          {o.label}
          {o.count !== undefined ? ` ${o.count}` : ""}
        </button>
      ))}
    </div>
  );
}

// ---- tables -------------------------------------------------------------------------------------------------------------------

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Keeps a date, a number or a reference on one line. */
  nowrap?: boolean;
  /** A value to sort by. Without it the column is not sortable. */
  sort?: (row: T) => string | number | null;
  num?: boolean;
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  onRowClick,
  searchText,
  searchPlaceholder = "Search",
  pageSize = 25,
  initialSort,
  empty = "Nothing to show.",
  toolbar,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** The text a search matches in a row. Without it there is no search box. */
  searchText?: (row: T) => string;
  searchPlaceholder?: string;
  pageSize?: number;
  initialSort?: { key: string; desc?: boolean };
  empty?: ReactNode;
  toolbar?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(1);

  const shown = useMemo(() => {
    let list = rows;
    const q = query.trim().toLowerCase();
    if (q && searchText) list = list.filter((r) => searchText(r).toLowerCase().includes(q));
    const col = columns.find((c) => c.key === sort?.key);
    if (col?.sort && sort) {
      const by = col.sort;
      const dir = sort.desc ? -1 : 1;
      list = [...list].sort((a, b) => {
        const x = by(a);
        const y = by(b);
        if (x === y) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        return (x < y ? -1 : 1) * dir;
      });
    }
    return list;
  }, [rows, query, sort, columns, searchText]);

  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pages);
  const slice = shown.slice((current - 1) * pageSize, current * pageSize);

  return (
    <>
      {(searchText || toolbar) && (
        <div className="pf-tablebar">
          {searchText && (
            <input
              type="search"
              value={query}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
            />
          )}
          {toolbar}
        </div>
      )}
      {slice.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <div className="pf-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    className={c.num ? "num" : ""}
                    aria-sort={
                      sort?.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"
                    }
                  >
                    {c.sort ? (
                      <button
                        type="button"
                        onClick={() =>
                          setSort(
                            sort?.key === c.key ? { key: c.key, desc: !sort.desc } : { key: c.key },
                          )
                        }
                      >
                        {c.header}
                        {sort?.key === c.key &&
                          (sort.desc ? <ChevronDown size={13} /> : <ChevronUp size={13} />)}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr
                  key={rowKey(r)}
                  className={onRowClick ? "click" : ""}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.num ? "num" : c.nowrap ? "nw" : ""}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {shown.length > pageSize && (
        <Pager
          page={current}
          pages={pages}
          total={shown.length}
          pageSize={pageSize}
          onPage={setPage}
        />
      )}
    </>
  );
}

export function Pager({
  page,
  pages,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const from = (page - 1) * pageSize + 1;
  return (
    <div className="pf-pager">
      <span>
        {from} to {Math.min(total, page * pageSize)} of {total}
      </span>
      <div className="pf-actions">
        <button
          className="pf-btn small"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft size={14} />
        </button>
        <span style={{ alignSelf: "center" }}>
          Page {page} of {pages}
        </span>
        <button
          className="pf-btn small"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
          aria-label="Next page"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

// ---- dialogs ------------------------------------------------------------------------------------------------------------------

/** A dialog that takes a few answers and does one thing. Esc and the backdrop cancel; the button is held while it works; a refusal is shown
 *  in the dialog so nothing typed is lost. Anything that changes a customer asks for a reason, which goes in their audit trail. */
export function FormDialog({
  title,
  description,
  submitLabel,
  danger,
  onSubmit,
  onClose,
  children,
}: {
  title: string;
  description?: ReactNode;
  submitLabel: string;
  danger?: boolean;
  onSubmit: () => Promise<void>;
  onClose: () => void;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    box.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div
      className="pf-overlay"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div className="pf-dialog" role="dialog" aria-modal="true" aria-label={title} ref={box}>
        <form onSubmit={submit}>
          <header>
            <h2>{title}</h2>
            {description && <p>{description}</p>}
          </header>
          <div className="pf-body">
            {children}
            {error && (
              <div className="pf-error" role="alert">
                {error}
              </div>
            )}
          </div>
          <footer>
            <button className="pf-btn" type="button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className={`pf-btn ${danger ? "danger solid" : "primary"}`} disabled={busy}>
              {busy ? "Working..." : submitLabel}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}

export function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="pf-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

/** The "why" every change to a customer needs: at least 3 characters, kept in their audit trail. */
export function ReasonField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <FormField
      label="Reason"
      hint="Written to the customer's audit trail, so the owner can see why."
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        minLength={3}
        maxLength={255}
        required
        rows={2}
      />
    </FormField>
  );
}

export function SearchIcon() {
  return <Search size={16} />;
}

export function CloseIcon() {
  return <X size={16} />;
}
