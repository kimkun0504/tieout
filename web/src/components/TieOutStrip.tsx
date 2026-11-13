import { fieldLabel, fmtMoney, fmtNumber } from "../lib/format";
import type { Result } from "../lib/types";
import { Check } from "./JobsPage";

/** Every total in the file, reported vs. what its units add up to. */
export function TieOutStrip({ result, onSelect }: { result: Result; onSelect: (row: number, field: string) => void }) {
  if (result.totals.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-rule bg-surface px-4 py-3 text-sm text-ink-2">
        This file has no total rows, so there is nothing to tie out. Check the unit count and rent against the source
        system before relying on it.
      </div>
    );
  }
  const issueFor = (row: number, field: string) =>
    result.issues.find((i) => i.row === row && i.field === field && i.rule.startsWith("total_"));

  return (
    <section aria-label="Totals" className="rounded-md border border-rule bg-surface">
      <div className="flex items-baseline gap-3 border-b border-rule-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold">Totals in the file</h2>
        <p className="text-sm text-ink-3">Each reported total compared with the sum of the units it covers</p>
      </div>
      <div className="flex gap-px overflow-x-auto bg-rule-soft">
        {result.totals.map((t) =>
          Object.entries(t.amounts).map(([field, reported]) => {
            const issue = issueFor(t.row, field);
            const state = issue?.acknowledgment
              ? "accepted"
              : issue?.rule === "total_ties_out"
                ? "ties"
                : issue
                  ? "off"
                  : "ties";
            const computed = t.computed[field];
            const fmt = field === "sqft" ? fmtNumber : fmtMoney;
            const diff = reported.value !== null && computed !== undefined ? Number(reported.value) - Number(computed) : null;
            return (
              <button
                key={`${t.row}-${field}`}
                onClick={() => onSelect(t.row, field)}
                className={`min-w-[12rem] flex-1 bg-surface px-4 py-3 text-left hover:bg-paper ${
                  state === "off" ? "shadow-[inset_0_-3px_0_var(--color-err)]" : ""
                }`}
              >
                <div className="flex items-center gap-2 text-sm text-ink-2">
                  <span className="truncate">
                    {t.label}, {fieldLabel(field === "charge_amount" ? "total_charges" : field).toLowerCase()}
                  </span>
                  <span className="ml-auto text-xs text-ink-3">row {t.row}</span>
                </div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-lg font-semibold">{reported.value === null ? "–" : fmt(reported.value)}</span>
                  {state === "ties" && (
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-tie">
                      <Check /> ties
                    </span>
                  )}
                  {state === "accepted" && <span className="text-sm text-ink-3">accepted</span>}
                </div>
                {state === "off" && (
                  <div className="text-sm text-err">
                    {reported.value === null
                      ? "Can't be checked"
                      : `Units add to ${fmt(computed ?? null)}, off by ${fmt(diff)}`}
                  </div>
                )}
              </button>
            );
          }),
        )}
      </div>
    </section>
  );
}
