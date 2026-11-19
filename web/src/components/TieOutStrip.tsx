import { fieldLabel, fmtMoney, fmtNumber } from "../lib/format";
import type { Issue, ReportedTotal, Result, StatedFigure } from "../lib/types";
import { Check } from "./JobsPage";

type State = "ties" | "off" | "accepted";

function stateOf(issue: Issue | undefined, tiesRule: string): State {
  if (issue?.acknowledgment) return "accepted";
  if (!issue || issue.rule === tiesRule) return "ties";
  return "off";
}

/** Every total and footer figure in the file, reported vs. what its units add up to. */
export function TieOutStrip({ result, onSelect }: { result: Result; onSelect: (row: number, field: string) => void }) {
  const figures = result.stated_figures ?? [];
  if (result.totals.length === 0 && figures.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-rule bg-surface px-4 py-3 text-sm text-ink-2">
        This file has no total rows, so there is nothing to tie out. Check the unit count and rent against the source
        system before relying on it.
      </div>
    );
  }
  const totalsWithAmounts = result.totals.filter((t) => Object.keys(t.amounts).length > 0);
  const off =
    result.issues.filter(
      (i) => !i.acknowledgment && (i.rule.startsWith("total_") || i.rule === "stated_figure_differs") && i.rule !== "total_ties_out",
    ).length;

  return (
    <section aria-label="Totals" className="rounded-md border border-rule bg-surface">
      <div className="flex flex-wrap items-baseline gap-x-3 border-b border-rule-soft px-4 py-2.5">
        <h2 className="text-sm font-semibold">Totals in the file</h2>
        <p className="text-sm text-ink-3">
          Each reported total and footer figure compared with the units it covers
          {off > 0 ? `; ${off} ${off === 1 ? "doesn't" : "don't"} agree` : ""}
        </p>
      </div>
      <div className="flex gap-px overflow-x-auto bg-rule-soft">
        {totalsWithAmounts.map((t) => (
          <TotalCard key={t.row} total={t} result={result} onSelect={onSelect} />
        ))}
        {figures.length > 0 && <FooterCard figures={figures} result={result} />}
      </div>
    </section>
  );
}

function TotalCard({
  total: t,
  result,
  onSelect,
}: {
  total: ReportedTotal;
  result: Result;
  onSelect: (row: number, field: string) => void;
}) {
  const issueFor = (field: string) =>
    result.issues.find((i) => i.row === t.row && i.field === field && i.rule.startsWith("total_"));
  return (
    <div className="min-w-[15rem] flex-1 bg-surface px-4 py-3">
      <div className="mb-1.5 flex items-baseline gap-2">
        <h3 className="truncate text-sm font-semibold" title={t.label}>
          {t.label}
        </h3>
        <span className="ml-auto shrink-0 text-xs text-ink-3">row {t.row}</span>
      </div>
      <ul className="space-y-0.5">
        {Object.entries(t.amounts).map(([field, reported]) => {
          const issue = issueFor(field);
          const state = stateOf(issue, "total_ties_out");
          const computed = t.computed[field];
          const fmt = field === "sqft" ? fmtNumber : fmtMoney;
          const diff =
            reported.value !== null && computed !== undefined ? Number(reported.value) - Number(computed) : null;
          const name = fieldLabel(field === "charge_amount" ? "charges" : field);
          return (
            <li key={field}>
              <button
                onClick={() => onSelect(t.row, field)}
                aria-label={`${t.label}, ${name.toLowerCase()}: ${state === "off" ? "doesn't tie" : state}`}
                className={`-mx-1.5 flex w-[calc(100%+0.75rem)] items-baseline gap-2 rounded px-1.5 py-0.5 text-left hover:bg-paper ${
                  state === "off" ? "bg-err-soft" : ""
                }`}
              >
                <span className="text-sm text-ink-2">{name}</span>
                <span className="ml-auto font-semibold tabular-nums">
                  {reported.value === null ? "–" : fmt(reported.value)}
                </span>
                <StateMark state={state} />
              </button>
              {state === "off" && (
                <div className="pb-1 text-right text-xs text-err">
                  {reported.value === null
                    ? "Can't be checked"
                    : `Units add to ${fmt(computed ?? null)}, off by ${fmt(diff)}`}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function FooterCard({ figures, result }: { figures: StatedFigure[]; result: Result }) {
  return (
    <div className="min-w-[15rem] flex-1 bg-surface px-4 py-3">
      <div className="mb-1.5 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">Report footer</h3>
        <span className="ml-auto text-xs text-ink-3">figures the file states</span>
      </div>
      <ul className="space-y-0.5">
        {figures.map((f) => {
          const issue = result.issues.find((i) => i.rule.startsWith("stated_") && i.cells[0] === f.cell.cell);
          const state = stateOf(issue, "stated_figure_ties");
          const shown =
            f.stat === "occupancy" && typeof f.stated === "number" && f.stated <= 1
              ? `${(f.stated * 100).toFixed(1)}%`
              : String(f.stated ?? "–");
          return (
            <li key={f.cell.cell} title={issue?.message}>
              <div
                className={`-mx-1.5 flex items-baseline gap-2 rounded px-1.5 py-0.5 ${state === "off" ? "bg-warn-soft" : ""}`}
              >
                <span className="text-sm text-ink-2">{f.label}</span>
                <span className="ml-auto font-semibold tabular-nums">{shown}</span>
                <StateMark state={state} warn />
              </div>
              {state === "off" && issue && (
                <div className="pb-1 text-right text-xs text-warn">
                  {(issue.message.split(". ")[0] ?? "").replace(/^The report states .*?, but /, "But ")}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function StateMark({ state, warn = false }: { state: State; warn?: boolean }) {
  if (state === "ties")
    return (
      <span className="inline-flex w-14 shrink-0 items-center gap-1 text-xs font-medium text-tie">
        <Check /> ties
      </span>
    );
  if (state === "accepted") return <span className="w-14 shrink-0 text-xs text-ink-3">accepted</span>;
  return <span className={`w-14 shrink-0 text-xs font-medium ${warn ? "text-warn" : "text-err"}`}>off</span>;
}
