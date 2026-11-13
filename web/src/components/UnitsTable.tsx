import { useMemo, useState } from "react";
import { fieldLabel, fmtValue } from "../lib/format";
import { issuesByRow, type Selection } from "../lib/selection";
import type { Issue, Result, Row, TracedValue } from "../lib/types";

const NUMERIC = new Set(["money", "number"]);

export function UnitsTable({
  result,
  selection,
  onSelect,
}: {
  result: Result;
  selection: Selection;
  onSelect: (s: Selection) => void;
}) {
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [query, setQuery] = useState("");
  const problems = useMemo(() => issuesByRow(result), [result]);
  const types = useMemo(() => Object.fromEntries(result.fields.map((f) => [f.name, f.type])), [result.fields]);

  // Only show columns that have data in this file.
  const columns = useMemo(
    () => result.fields.map((f) => f.name).filter((name) => result.rows.some((r) => r.fields[name]?.value != null)),
    [result],
  );

  const q = query.trim().toLowerCase();
  const rows = result.rows.filter(
    (r) =>
      (!onlyProblems || problems.has(r.source_row)) &&
      (!q || [r.fields.unit?.value, r.fields.tenant?.value].some((v) => String(v ?? "").toLowerCase().includes(q))),
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a unit or tenant"
          aria-label="Find a unit or tenant"
          className="w-56 rounded border border-rule px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-1.5 text-sm text-ink-2">
          <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
          Only units with problems
        </label>
        <span className="ml-auto flex items-center gap-3 text-xs text-ink-2">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-derived" /> Filled by tieout
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm bg-corrected" /> Corrected
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm border-b-2 border-err bg-surface" /> Problem
          </span>
        </span>
      </div>
      <div className="max-h-[36rem] overflow-auto border-t border-rule-soft">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr>
              <th className="border-b border-rule px-3 py-2 text-left font-medium text-ink-3">Row</th>
              {columns.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className={`whitespace-nowrap border-b border-rule px-3 py-2 font-medium text-ink-3 ${
                    NUMERIC.has(types[c] ?? "") ? "text-right" : "text-left"
                  }`}
                >
                  {fieldLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const prev = rows[i - 1];
              const newSection = r.section && r.section !== prev?.section;
              return (
                <UnitRow
                  key={r.source_row}
                  row={r}
                  columns={columns}
                  types={types}
                  issues={problems.get(r.source_row)}
                  selection={selection}
                  onSelect={onSelect}
                  sectionLabel={newSection ? r.section : null}
                />
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className="px-4 py-6 text-sm text-ink-3">No units match.</p>}
      </div>
    </div>
  );
}

function UnitRow({
  row,
  columns,
  types,
  issues,
  selection,
  onSelect,
  sectionLabel,
}: {
  row: Row;
  columns: string[];
  types: Record<string, string>;
  issues: Issue[] | undefined;
  selection: Selection;
  onSelect: (s: Selection) => void;
  sectionLabel: string | null;
}) {
  const rowSelected = selection.row === row.source_row;
  const problemFields = new Set((issues ?? []).map((i) => i.field));
  return (
    <>
      {sectionLabel && (
        <tr>
          <th colSpan={columns.length + 1} className="bg-paper px-3 py-1.5 text-left text-sm font-semibold">
            {sectionLabel}
          </th>
        </tr>
      )}
      <tr className={rowSelected ? "bg-action/5" : "hover:bg-paper"}>
        <td className="border-b border-rule-soft px-3 py-1.5 text-xs text-ink-3">{row.source_row}</td>
        {columns.map((c) => {
          const tv = row.fields[c];
          const selected = rowSelected && selection.field === c;
          return (
            <td
              key={c}
              className={`border-b border-rule-soft p-0 ${cellTint(tv)} ${
                problemFields.has(c) || tv?.issue ? "shadow-[inset_0_-2px_0_var(--color-err)]" : ""
              }`}
            >
              <button
                onClick={() => onSelect({ row: row.source_row, field: c })}
                aria-label={`${fieldLabel(c)} for row ${row.source_row}`}
                className={`block w-full whitespace-nowrap px-3 py-1.5 ${
                  NUMERIC.has(types[c] ?? "") ? "text-right" : "text-left"
                } ${selected ? "outline outline-2 -outline-offset-2 outline-action" : ""}`}
              >
                {tv ? fmtValue(tv.value, types[c] as never) || (tv.issue ? "?" : "") : ""}
              </button>
            </td>
          );
        })}
      </tr>
    </>
  );
}

function cellTint(tv: TracedValue | undefined): string {
  if (!tv) return "";
  if (tv.correction) return "bg-corrected";
  if (tv.derived) return "bg-derived";
  return "";
}
