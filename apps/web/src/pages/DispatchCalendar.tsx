import type { CalendarBooking, CalendarDay, DispatchCalendar } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { nairobiTime, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const COLOUR: Record<CalendarDay["status"], string> = {
  free: "transparent",
  booked: "rgba(245, 158, 11, 0.35)",
  in_service: "rgba(220, 38, 38, 0.35)",
};
const LABEL: Record<CalendarDay["status"], string> = {
  free: "Free",
  booked: "Booked",
  in_service: "In service",
};

const addDays = (isoDate: string, days: number) => {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

function Row({
  name,
  note,
  days,
  bookings,
}: {
  name: string;
  note?: string;
  days: CalendarDay[];
  bookings: CalendarBooking[];
}) {
  const detail = bookings
    .map(
      (b) =>
        `${b.job_number ?? "Trip"} ${b.client_name ?? ""}: ${nairobiTime(b.from)} to ${nairobiTime(b.to)}`,
    )
    .join("\n");
  return (
    <tr>
      <th style={{ textAlign: "left", whiteSpace: "nowrap" }} title={detail}>
        {name}
        {note && (
          <>
            <br />
            <span className="muted">{note}</span>
          </>
        )}
      </th>
      {days.map((d) => (
        <td
          key={d.date}
          title={`${d.date}: ${LABEL[d.status]}${detail ? `\n${detail}` : ""}`}
          style={{ background: COLOUR[d.status], textAlign: "center", minWidth: 44 }}
        >
          {d.status === "free" ? "" : d.status === "booked" ? "B" : "S"}
        </td>
      ))}
    </tr>
  );
}

/** Which lorries and crew are free, booked or in service, day by day. */
export default function Calendar() {
  const [from, setFrom] = useState(todayIso());
  const [data, setData] = useState<DispatchCalendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api.calendar(from, addDays(from, 13)));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [from]);
  useEffect(() => {
    void load();
  }, [load]);

  const head = data?.vehicles[0]?.days ?? data?.crew[0]?.days ?? [];
  const bookings = [...(data?.vehicles ?? []), ...(data?.crew ?? [])].flatMap((x) => x.bookings);
  const seen = new Set<string>();
  const unique = bookings.filter((b) =>
    seen.has(b.trip_id) ? false : (seen.add(b.trip_id), true),
  );
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Dispatch calendar">
        <div className="form-grid">
          <Field label="From">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <button className="btn" onClick={() => setFrom(addDays(from, -7))}>
            Earlier
          </button>
          <button className="btn" onClick={() => setFrom(addDays(from, 7))}>
            Later
          </button>
        </div>
        <p className="muted">
          B booked, S in service (the lorry is in the workshop). Hover a cell for the jobs.
        </p>
        {data && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th />
                  {head.map((d) => (
                    <th key={d.date}>{d.date.slice(5)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.vehicles.map((v) => (
                  <Row
                    key={v.id}
                    name={v.registration}
                    note={v.service ? `In the workshop: ${v.service.title}` : undefined}
                    days={v.days}
                    bookings={v.bookings}
                  />
                ))}
                {data.crew.length > 0 && (
                  <tr>
                    <th colSpan={head.length + 1} style={{ textAlign: "left" }}>
                      Crew
                    </th>
                  </tr>
                )}
                {data.crew.map((c) => (
                  <Row
                    key={c.membership_id}
                    name={c.name}
                    note={c.role}
                    days={c.days}
                    bookings={c.bookings}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {unique.length > 0 && (
        <Card title="Bookings in this period">
          <ul className="list">
            {unique
              .sort((a, b) => a.from.localeCompare(b.from))
              .map((b) => (
                <li key={b.trip_id}>
                  <span>
                    {nairobiTime(b.from)} to {nairobiTime(b.to)}: {b.route ?? "trip"}
                    {b.client_name && `, ${b.client_name}`}
                    {b.driver_name && `, ${b.driver_name}`}
                  </span>
                  {b.job_id && <Link to={`/jobs/view/${b.job_id}`}>{b.job_number}</Link>}
                </li>
              ))}
          </ul>
        </Card>
      )}
    </>
  );
}
