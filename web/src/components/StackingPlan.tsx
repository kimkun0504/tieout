import { useMemo } from "react";
import { fmtPct } from "../lib/format";
import { issuesByRow, type Selection, worstSeverity } from "../lib/selection";
import type { Result, Row } from "../lib/types";

const STATUS_STYLE: Record<string, string> = {
  occupied: "bg-[#c9d6e3] border-[#c9d6e3] text-ink",
  notice: "bg-warn-soft border-warn/50 text-ink",
  vacant: "bg-surface border-ink-3/60 border-dashed text-ink-2",
  model: "bg-rule-soft border-rule text-ink-3",
  down: "bg-rule-soft border-rule text-ink-3",
  unknown: "bg-surface border-rule text-ink-3",
};

const LEGEND: [string, string][] = [
  ["occupied", "Occupied"],
  ["notice", "On notice"],
  ["vacant", "Vacant"],
  ["down", "Down or model"],
];

/**
 * The building as a stacking plan: one tile per unit, grouped by section
 * (building or floor), shaded by status. Units with open problems carry a
 * marker, so where the problems sit is visible before reading a list.
 */
export function StackingPlan({
  result,
  selection,
  onSelect,
}: {
  result: Result;
  selection: Selection;
  onSelect: (row: number) => void;
}) {
  const problems = useMemo(() => issuesByRow(result), [result]);
  const sections = useMemo(() => {
    const map = new Map<string, Row[]>();
    for (const r of result.rows) {
      const key = r.section ?? "";
      map.set(key, [...(map.get(key) ?? []), r]);
    }
    return [...map.entries()];
  }, [result.rows]);

  const flagged = [...problems.values()].length;
  return (
    <section aria-label="Units by status" className="min-w-0 rounded-md border border-rule bg-surface">
      <div className="flex items-baseline gap-3 border-b border-rule-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold">Stacking plan</h2>
        <p className="text-sm text-ink-3">
          {result.rows.length} units, {fmtPct(result.summary.physical_occupancy)} occupied
          {flagged > 0 && `, ${flagged} with problems`}
        </p>
      </div>
      <div className="max-h-80 space-y-3 overflow-y-auto px-4 py-3">
        {sections.map(([name, rows]) => (
          <div key={name || "_"}>
            {name && <h3 className="mb-1.5 text-sm font-medium text-ink-2">{name}</h3>}
            <div className="flex flex-wrap gap-1">
              {rows.map((r) => {
                const status = String(r.fields.status?.value ?? "unknown");
                const worst = worstSeverity(problems.get(r.source_row));
                const selected = selection.row === r.source_row;
                const unit = String(r.fields.unit?.value ?? r.source_row);
                return (
                  <button
                    key={r.source_row}
                    onClick={() => onSelect(r.source_row)}
                    title={`${unit}: ${status}${worst ? `, ${problems.get(r.source_row)!.length} open problem(s)` : ""}`}
                    aria-pressed={selected}
                    className={`relative h-8 min-w-[3.25rem] rounded-sm border px-1.5 text-xs font-medium ${
                      STATUS_STYLE[status] ?? STATUS_STYLE.unknown
                    } ${selected ? "outline outline-2 outline-offset-1 outline-action" : ""}`}
                  >
                    {unit}
                    {worst && (
                      <span
                        aria-label={worst === "error" ? "has errors" : "has warnings"}
                        className={`absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-surface ${
                          worst === "error" ? "bg-err" : "bg-warn"
                        }`}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-rule-soft px-4 py-2 text-xs text-ink-2">
        {LEGEND.map(([key, label]) => (
          <span key={key} className="inline-flex items-center gap-1.5">
            <span className={`inline-block h-3 w-4 rounded-sm border ${STATUS_STYLE[key]}`} />
            {label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-err" /> Error
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-warn" /> Warning
        </span>
      </div>
    </section>
  );
}
