/** Small SVG charts for the console: no chart library, so nothing to load and nothing to go out of date. Each has a text alternative. */

export const BLUE = "#2563eb";
export const GREEN = "#0f9d58";
export const AMBER = "#f59e0b";
export const VIOLET = "#7c3aed";
export const TEAL = "#0e7490";
export const RED = "#d92d20";
export const SLATE = "#64748b";
const PALETTE = [BLUE, GREEN, AMBER, VIOLET, TEAL, RED, SLATE];
const colorAt = (i: number) => PALETTE[i % PALETTE.length] ?? SLATE;

/** A round upper limit and tick marks for a value axis (0, 50k, 100k...). */
function niceScale(max: number, ticks = 4): { top: number; marks: number[] } {
  if (max <= 0) return { top: 1, marks: [0, 1] };
  const raw = max / ticks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const top = step * Math.ceil(max / step);
  const marks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) marks.push(v);
  return { top, marks };
}

/** "Oct" from "2026-10". */
export function monthLabel(key: string): string {
  const [year = 1970, month = 1] = key.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleString("en-GB", {
    month: "short",
    timeZone: "UTC",
  });
}

export interface Series {
  key: string;
  label: string;
  color: string;
}

export function BarChart({
  data,
  series,
  format,
  height = 220,
  summary,
}: {
  data: { label: string; values: Record<string, number> }[];
  series: Series[];
  format: (value: number) => string;
  height?: number;
  /** What the chart says in words, for a screen reader. */
  summary: string;
}) {
  const width = 640;
  const pad = { left: 52, right: 8, top: 10, bottom: 24 };
  const totals = data.map((d) => series.reduce((sum, s) => sum + (d.values[s.key] ?? 0), 0));
  const { top, marks } = niceScale(Math.max(0, ...totals));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const slot = innerW / Math.max(1, data.length);
  const barW = Math.min(36, slot * 0.64);
  const y = (v: number) => pad.top + innerH - (v / top) * innerH;
  return (
    <>
      <svg className="pf-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary}>
        {marks.map((m) => (
          <g key={m}>
            <line className="grid" x1={pad.left} x2={width - pad.right} y1={y(m)} y2={y(m)} />
            <text x={pad.left - 8} y={y(m) + 4} textAnchor="end">
              {format(m)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = pad.left + slot * i + (slot - barW) / 2;
          let acc = 0;
          return (
            <g key={d.label}>
              {series.map((s) => {
                const v = d.values[s.key] ?? 0;
                const h = (v / top) * innerH;
                const rect = (
                  <rect
                    key={s.key}
                    x={x}
                    y={y(acc + v)}
                    width={barW}
                    height={Math.max(0, h)}
                    rx={2}
                    fill={s.color}
                  >
                    <title>{`${d.label}, ${s.label}: ${format(v)}`}</title>
                  </rect>
                );
                acc += v;
                return rect;
              })}
              <text x={x + barW / 2} y={height - 7} textAnchor="middle">
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
      {series.length > 1 && (
        <div className="pf-legend">
          {series.map((s) => (
            <span key={s.key}>
              <i style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

export function LineChart({
  data,
  format,
  color = BLUE,
  height = 200,
  summary,
}: {
  data: { label: string; value: number }[];
  format: (value: number) => string;
  color?: string;
  height?: number;
  summary: string;
}) {
  const width = 640;
  const pad = { left: 52, right: 12, top: 12, bottom: 24 };
  const { top, marks } = niceScale(Math.max(0, ...data.map((d) => d.value)));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const x = (i: number) =>
    pad.left + (data.length <= 1 ? innerW / 2 : (innerW * i) / (data.length - 1));
  const y = (v: number) => pad.top + innerH - (v / top) * innerH;
  const line = data
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.value).toFixed(1)}`)
    .join(" ");
  const area = data.length > 1 ? `${line} L${x(data.length - 1)},${y(0)} L${x(0)},${y(0)} Z` : "";
  return (
    <svg className="pf-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary}>
      {marks.map((m) => (
        <g key={m}>
          <line className="grid" x1={pad.left} x2={width - pad.right} y1={y(m)} y2={y(m)} />
          <text x={pad.left - 8} y={y(m) + 4} textAnchor="end">
            {format(m)}
          </text>
        </g>
      ))}
      {area && <path d={area} fill={color} opacity={0.12} />}
      <path d={line} fill="none" stroke={color} strokeWidth={2.2} strokeLinejoin="round" />
      {data.map((d, i) => (
        <g key={d.label}>
          <circle cx={x(i)} cy={y(d.value)} r={3.5} fill={color}>
            <title>{`${d.label}: ${format(d.value)}`}</title>
          </circle>
          <text x={x(i)} y={height - 7} textAnchor="middle">
            {d.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function Donut({
  slices,
  format = (v) => String(v),
  size = 150,
  summary,
}: {
  slices: { label: string; value: number; color?: string }[];
  format?: (value: number) => string;
  size?: number;
  summary: string;
}) {
  const live = slices.filter((s) => s.value > 0);
  const total = live.reduce((sum, s) => sum + s.value, 0);
  const r = size / 2 - 10;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="pf-donut">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={summary}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--pf-border)"
          strokeWidth={18}
        />
        {total > 0 &&
          live.map((s, i) => {
            const len = (s.value / total) * c;
            const el = (
              <circle
                key={s.label}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={s.color ?? colorAt(i)}
                strokeWidth={18}
                strokeDasharray={`${Math.max(0, len - 1.5)} ${c - len + 1.5}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              >
                <title>{`${s.label}: ${format(s.value)}`}</title>
              </circle>
            );
            offset += len;
            return el;
          })}
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="central"
          style={{ fontSize: 20, fontWeight: 700, fill: "var(--pf-text)" }}
        >
          {format(total)}
        </text>
      </svg>
      <ul>
        {slices.map((s, i) => (
          <li key={s.label}>
            <i style={{ background: s.color ?? colorAt(i) }} />
            {s.label}
            <b>{format(s.value)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}
