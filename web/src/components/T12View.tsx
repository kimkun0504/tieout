import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtMoney, fmtMonth, fmtPct } from "../lib/format";
import type { Issue, T12Line, T12Response } from "../lib/types";
import { ComparePanel } from "./ComparePanel";
import { Check } from "./JobsPage";
import { IssueItem } from "./IssueQueue";
import { Empty } from "./ui";

const CHECKS: { rule: string; title: string; what: string }[] = [
  { rule: "t12_row_total_mismatch", title: "Across", what: "Each line's months add up to its Total" },
  { rule: "t12_subtotal_mismatch", title: "Down", what: "Each subtotal equals its lines, every month" },
  { rule: "t12_noi_mismatch", title: "Through", what: "NOI is income minus expenses, every month" },
];

const SECTION_LABEL: Record<string, string> = {
  income: "Income",
  expense: "Expenses",
  other: "Other",
  below_noi: "Below NOI",
  noi: "",
};

function categoryLabel(c: string): string {
  return c.replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase());
}

export function T12View({ data }: { data: T12Response }) {
  const { job, result } = data;
  const s = result.summary;
  const [selected, setSelected] = useState<string | null>(null); // a cell address, e.g. "D28"

  // Cells named by open errors and warnings, to mark them in the grid.
  const flagged = useMemo(() => {
    const map = new Map<string, Issue>();
    for (const i of result.issues) if (i.severity !== "info") for (const c of i.cells) map.set(c, i);
    return map;
  }, [result.issues]);

  useEffect(() => {
    if (selected) document.querySelector(`[data-addr="${selected}"]`)?.scrollIntoView({ block: "center", inline: "center" });
  }, [selected]);

  const income = Number(s.total_income);
  return (
    <main className="space-y-4 px-5 py-5">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="min-w-0">
          <a href="#/" className="text-sm text-ink-3 hover:text-ink">
            All files
          </a>
          <h1 className="truncate text-xl font-semibold tracking-tight">{job.filename}</h1>
          <p className="text-sm text-ink-3">
            Operating statement, {s.period}, sheet {result.source.sheet}
          </p>
        </div>
        <div aria-live="polite">
          {result.ok ? (
            <span className="inline-flex items-center gap-1.5 rounded bg-tie-soft px-2.5 py-1 font-semibold text-tie">
              <Check /> Ties out
            </span>
          ) : (
            <span className="rounded bg-err-soft px-2.5 py-1 font-semibold text-err">
              {s.errors} {s.errors === 1 ? "error" : "errors"} to resolve
            </span>
          )}
        </div>
        <details className="relative ml-auto">
          <summary className="cursor-pointer list-none rounded bg-action px-3 py-1.5 text-sm font-medium text-white hover:bg-action-hover">
            Export
          </summary>
          <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-rule bg-surface py-1 shadow-lg">
            {(
              [
                ["xlsx", "Excel workbook"],
                ["csv", "Tidy CSV (one row per month)"],
                ["json", "JSON with sources"],
                ["report", "Summary report"],
              ] as const
            ).map(([fmt, label]) => (
              <a key={fmt} href={api.exportUrl(job.id, fmt)} download className="block px-3 py-1.5 text-sm hover:bg-paper">
                {label}
              </a>
            ))}
          </div>
        </details>
      </div>

      <section aria-label="Tie-out checks" className="grid gap-px overflow-hidden rounded-md border border-rule bg-rule-soft sm:grid-cols-3">
        {CHECKS.map((c) => {
          const all = result.issues.filter((i) => i.rule === c.rule);
          const misses = all.filter((i) => !i.acknowledgment);
          return (
            <div key={c.rule} className={`bg-surface px-4 py-3 ${misses.length ? "shadow-[inset_0_-3px_0_var(--color-err)]" : ""}`}>
              <div className="text-sm text-ink-2">
                <span className="font-semibold text-ink">{c.title}.</span> {c.what}
              </div>
              {misses.length === 0 ? (
                <div className="mt-1 inline-flex items-center gap-1 font-medium text-tie">
                  <Check /> {all.length ? `${all.length} accepted` : "ties"}
                </div>
              ) : (
                <button
                  className="mt-1 text-left text-sm font-medium text-err hover:underline"
                  onClick={() => setSelected(misses[0]!.cells[0] ?? null)}
                >
                  {misses.length} {misses.length === 1 ? "place doesn't" : "places don't"} tie out
                </button>
              )}
            </div>
          );
        })}
      </section>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section aria-label="Statement" className="min-w-0 rounded-md border border-rule bg-surface">
          <div className="flex items-baseline gap-3 border-b border-rule-soft px-4 py-2.5">
            <h2 className="text-sm font-semibold">Statement</h2>
            <p className="text-sm text-ink-3">{s.line_items} line items; problem cells are underlined</p>
          </div>
          <div className="max-h-[40rem] overflow-auto" tabIndex={0} aria-label="Statement table, scrollable">
            <table className="border-separate border-spacing-0 text-sm">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <th className="sticky left-0 z-20 border-b border-rule bg-surface px-3 py-2 text-left font-medium text-ink-3">
                    Line item
                  </th>
                  {result.months.map((m) => (
                    <th key={m} className="whitespace-nowrap border-b border-rule px-3 py-2 text-right font-medium text-ink-3">
                      {fmtMonth(m)}
                    </th>
                  ))}
                  <th className="border-b border-rule px-3 py-2 text-right font-medium text-ink-3">Total</th>
                </tr>
              </thead>
              <tbody>
                {result.lines.map((ln, i) => (
                  <StatementRow
                    key={ln.source_row}
                    line={ln}
                    sectionStart={ln.section !== result.lines[i - 1]?.section ? SECTION_LABEL[ln.section] : undefined}
                    width={result.months.length + 2}
                    flagged={flagged}
                    selected={selected}
                    onSelect={setSelected}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="space-y-4">
          <section aria-label="Summary" className="rounded-md border border-rule bg-surface">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3">
              {(
                [
                  ["Total income", fmtMoney(s.total_income)],
                  ["Total expenses", fmtMoney(s.total_expenses)],
                  ["Net operating income", fmtMoney(s.noi)],
                  ["Expense ratio", fmtPct(s.expense_ratio)],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-sm text-ink-2">{label}</dt>
                  <dd className="text-lg font-semibold">{value}</dd>
                </div>
              ))}
            </dl>
            <table className="w-full border-t border-rule-soft text-sm">
              <caption className="px-4 pt-2.5 text-left text-sm text-ink-2">By standard category, 12 months</caption>
              <tbody>
                {Object.entries(s.by_category)
                  .sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))
                  .map(([cat, amount]) => (
                    <tr key={cat} className="border-t border-rule-soft">
                      <td className="px-4 py-1.5">{categoryLabel(cat)}</td>
                      <td className="px-2 py-1.5 text-right">{fmtMoney(amount)}</td>
                      <td className="px-4 py-1.5 text-right text-ink-3">{income ? fmtPct(Number(amount) / income) : ""}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {s.uncategorized > 0 && (
              <p className="border-t border-rule-soft px-4 py-2 text-sm text-warn">
                {s.uncategorized} line {s.uncategorized === 1 ? "item has" : "items have"} no standard category.
              </p>
            )}
          </section>

          <ComparePanel t12Id={job.id} />

          <section aria-label="Issues" className="rounded-md border border-rule bg-surface">
            <h2 className="border-b border-rule-soft px-4 py-2.5 text-sm font-semibold">To review</h2>
            {result.issues.length === 0 ? (
              <Empty>Nothing to review. Every line, subtotal and NOI ties out.</Empty>
            ) : (
              <ul className="max-h-96 divide-y divide-rule-soft overflow-y-auto">
                {result.issues.map((i) => (
                  <IssueItem key={i.id} jobId={job.id} issue={i} onSelect={() => setSelected(i.cells[0] ?? null)} />
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function StatementRow({
  line,
  sectionStart,
  width,
  flagged,
  selected,
  onSelect,
}: {
  line: T12Line;
  sectionStart: string | undefined;
  width: number;
  flagged: Map<string, Issue>;
  selected: string | null;
  onSelect: (cell: string) => void;
}) {
  const strong = line.kind !== "line";
  const cell = (value: string | null, address: string | null, key: string) => {
    const issue = address ? flagged.get(address) : undefined;
    const isSelected = address !== null && address === selected;
    return (
      <td
        key={key}
        data-addr={address ?? undefined}
        title={address ? `${address}${issue ? `: ${issue.message}` : ""}` : undefined}
        className={`whitespace-nowrap border-b border-rule-soft px-3 py-1.5 text-right ${
          issue ? (issue.severity === "error" ? "shadow-[inset_0_-2px_0_var(--color-err)]" : "shadow-[inset_0_-2px_0_var(--color-warn)]") : ""
        } ${isSelected ? "outline outline-2 -outline-offset-2 outline-action" : ""}`}
        onClick={() => address && onSelect(address)}
      >
        {fmtMoney(value)}
      </td>
    );
  };
  return (
    <>
      {sectionStart && (
        <tr>
          <th colSpan={width} className="bg-paper px-3 py-1.5 text-left text-sm font-semibold">
            {sectionStart}
          </th>
        </tr>
      )}
      <tr className={strong ? "bg-rule-soft/50 font-semibold" : "hover:bg-paper"}>
        <th
          scope="row"
          className={`sticky left-0 whitespace-nowrap border-b border-rule-soft bg-surface px-3 py-1.5 text-left ${
            strong ? "font-semibold" : "font-normal"
          }`}
        >
          {line.code && <span className="mr-2 text-xs text-ink-3">{line.code}</span>}
          {line.name}
          {line.kind === "line" && !line.category && line.section !== "below_noi" && (
            <span className="ml-2 text-xs text-warn">no category</span>
          )}
        </th>
        {line.amounts.map((a, i) => cell(a, line.cells[i] ?? null, String(i)))}
        {cell(line.total, line.total_cell, "total")}
      </tr>
    </>
  );
}
