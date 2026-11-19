import { fmtDate, fmtMoney, fmtMonth, fmtNumber, fmtPct } from "../lib/format";
import type { Metrics as M, Result } from "../lib/types";

export function Metrics({ result }: { result: Result }) {
  const m = result.metrics;
  const rows: [string, string, string?][] = [
    ["Physical occupancy", fmtPct(m.physical_occupancy), `${m.occupied_units} of ${m.units} units`],
    ["Economic occupancy", fmtPct(m.economic_occupancy), "In-place rent over market rent"],
    ["Gross potential rent", fmtMoney(m.gross_potential_rent), "Market rent, all units"],
    ["In-place rent", fmtMoney(m.in_place_rent), "Occupied units"],
    [
      "Loss to lease",
      fmtMoney(m.loss_to_lease),
      m.loss_to_lease_pct !== null ? `${fmtPct(m.loss_to_lease_pct)} below market` : undefined,
    ],
    ["Vacancy loss", fmtMoney(m.vacancy_loss)],
    ["Concessions", fmtMoney(m.concessions)],
    ["Average rent", fmtMoney(m.avg_in_place_rent), m.avg_rent_per_sqft ? `${fmtMoney(m.avg_rent_per_sqft)} per sq ft` : undefined],
  ];
  return (
    <section aria-label="Rent roll metrics" className="min-w-0 rounded-md border border-rule bg-surface">
      <div className="flex items-baseline gap-3 border-b border-rule-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold">Monthly figures</h2>
        <p className="text-sm text-ink-3">From cleaned values, including your corrections</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3">
        {rows
          .filter(([, value]) => value && value !== "–")
          .map(([label, value, note]) => (
            <div key={label} className="min-w-0">
              <dt className="text-sm text-ink-2">{label}</dt>
              <dd className="text-lg font-semibold leading-tight">{value}</dd>
              {note && <dd className="truncate text-xs text-ink-3">{note}</dd>}
            </div>
          ))}
      </dl>
      {m.lease_expirations ? <Expirations exp={m.lease_expirations} /> : <NoAsOf />}
      {m.unit_mix.length > 1 && <UnitMix mix={m.unit_mix} />}
    </section>
  );
}

function NoAsOf() {
  return (
    <p className="border-t border-rule-soft px-4 py-2.5 text-sm text-ink-3">
      Set a report date to see lease expirations for the next 12 months.
    </p>
  );
}

function Expirations({ exp }: { exp: NonNullable<M["lease_expirations"]> }) {
  const max = Math.max(1, ...exp.by_month.map((b) => b.units));
  return (
    <figure className="border-t border-rule-soft px-4 py-3">
      <figcaption className="mb-2 text-sm text-ink-2">
        Leases expiring in the 12 months from {fmtDate(exp.as_of)}
        {exp.expired_or_mtm > 0 && <span className="text-warn">, {exp.expired_or_mtm} already expired or month to month</span>}
      </figcaption>
      <div className="flex h-20 items-end gap-1" role="list">
        {exp.by_month.map((b) => (
          <div
            key={b.month}
            role="listitem"
            aria-label={`${fmtMonth(b.month)}: ${b.units} leases`}
            className="flex flex-1 flex-col items-center justify-end gap-1"
          >
            {b.units > 0 && <span className="text-xs text-ink-2">{b.units}</span>}
            <div className="w-full rounded-t-sm bg-action/70" style={{ height: `${(b.units / max) * 48}px` }} />
            <span className="text-[0.65rem] text-ink-3">{fmtMonth(b.month).split(" ")[0]}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function UnitMix({ mix }: { mix: M["unit_mix"] }) {
  return (
    <div className="overflow-x-auto border-t border-rule-soft">
      <table className="w-full text-sm">
        <caption className="px-4 pt-2.5 text-left text-sm text-ink-2">Unit mix</caption>
        <thead className="text-ink-3">
          <tr>
            <th className="px-4 py-1.5 text-left font-medium">Type</th>
            <th className="px-2 py-1.5 text-right font-medium">Units</th>
            <th className="px-2 py-1.5 text-right font-medium">Occupied</th>
            <th className="px-2 py-1.5 text-right font-medium">Sq ft</th>
            <th className="px-2 py-1.5 text-right font-medium">Market</th>
            <th className="px-4 py-1.5 text-right font-medium">In place</th>
          </tr>
        </thead>
        <tbody>
          {mix.map((u) => (
            <tr key={u.unit_type} className="border-t border-rule-soft">
              <td className="px-4 py-1.5">{u.unit_type}</td>
              <td className="px-2 py-1.5 text-right">{u.units}</td>
              <td className="px-2 py-1.5 text-right">{fmtPct(u.occupancy, 0)}</td>
              <td className="px-2 py-1.5 text-right">{fmtNumber(u.avg_sqft)}</td>
              <td className="px-2 py-1.5 text-right">{fmtMoney(u.avg_market_rent)}</td>
              <td className="px-4 py-1.5 text-right">{fmtMoney(u.avg_in_place_rent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
