import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { fmtMoney, fmtMonth, fmtPct } from "../lib/format";
import type { ComparisonCheck } from "../lib/types";
import { Check } from "./JobsPage";
import { ErrorNote } from "./ui";

const STATUS: Record<ComparisonCheck["status"], { label: string; className: string }> = {
  consistent: { label: "Consistent", className: "text-tie" },
  check: { label: "Worth a look", className: "text-warn" },
  investigate: { label: "Investigate", className: "text-err" },
  unavailable: { label: "Not available", className: "text-ink-3" },
};

function show(c: ComparisonCheck, v: string | null): string {
  if (v === null) return "–";
  return c.metric === "economic_occupancy" ? fmtPct(Number(v)) : fmtMoney(v);
}

/** Does this T-12 agree with a rent roll for the same property? */
export function ComparePanel({ t12Id }: { t12Id: string }) {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs });
  const rentRolls = (jobs.data ?? []).filter((j) => (j.document_type ?? "rent_roll") === "rent_roll");
  const [rentRoll, setRentRoll] = useState("");
  const result = useQuery({
    queryKey: ["compare", rentRoll, t12Id],
    queryFn: () => api.compare(rentRoll, t12Id),
    enabled: !!rentRoll,
  });

  return (
    <section aria-label="Compare with a rent roll" className="rounded-md border border-rule bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-rule-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold">Compare with a rent roll</h2>
        <select
          value={rentRoll}
          onChange={(e) => setRentRoll(e.target.value)}
          aria-label="Rent roll to compare"
          className="ml-auto rounded border border-rule px-2 py-1 text-sm"
        >
          <option value="">Choose a rent roll…</option>
          {rentRolls.map((j) => (
            <option key={j.id} value={j.id}>
              {j.filename}
            </option>
          ))}
        </select>
      </div>
      {!rentRoll && (
        <p className="px-4 py-3 text-sm text-ink-2">
          Pick the rent roll for this property to check that market rent, rent in place and occupancy agree with the
          statement's last month.{rentRolls.length === 0 && " Upload a rent roll first."}
        </p>
      )}
      {result.error && (
        <div className="p-4">
          <ErrorNote error={result.error} />
        </div>
      )}
      {result.data && (
        <>
          <table className="w-full text-sm">
            <thead className="text-ink-3">
              <tr>
                <th className="px-4 py-1.5 text-left font-medium" />
                <th className="px-2 py-1.5 text-right font-medium">Rent roll</th>
                <th className="px-2 py-1.5 text-right font-medium">
                  T-12, {result.data.t12.last_month ? fmtMonth(result.data.t12.last_month) : ""}
                </th>
                <th className="px-4 py-1.5 text-right font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {result.data.checks.map((c) => (
                <tr key={c.metric} className="border-t border-rule-soft align-top" title={c.explanation}>
                  <th scope="row" className="px-4 py-2 text-left font-normal">
                    {c.label}
                  </th>
                  <td className="px-2 py-2 text-right">{show(c, c.rent_roll)}</td>
                  <td className="px-2 py-2 text-right">{show(c, c.t12)}</td>
                  <td className={`px-4 py-2 text-right font-medium ${STATUS[c.status].className}`}>
                    {c.status === "consistent" ? (
                      <span className="inline-flex items-center gap-1">
                        <Check /> {STATUS[c.status].label}
                      </span>
                    ) : (
                      STATUS[c.status].label
                    )}
                    {c.pct !== null && c.status !== "consistent" && (
                      <span className="block text-xs font-normal text-ink-3">{fmtPct(c.pct)} apart</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-rule-soft px-4 py-2.5 text-xs text-ink-3">
            {result.data.timing
              ? `Rent roll dated ${result.data.timing.rent_roll_as_of}, ${Math.abs(result.data.timing.months_apart)} month(s) from the statement's last month. `
              : "Set a report date on the rent roll to check timing. "}
            Within 2% is consistent; beyond 5% needs explaining. Hover a row for what it compares.
          </p>
        </>
      )}
    </section>
  );
}
