import { useEffect, useMemo, useRef } from "react";
import { useSource } from "../lib/hooks";
import { colLetter, type Selection } from "../lib/selection";
import type { Result } from "../lib/types";
import { Empty, ErrorNote } from "./ui";

const MAX_RENDER_ROWS = 1500;

/** The sheet exactly as uploaded, with the selected value's cell highlighted. */
export function SourceView({ jobId, result, selection }: { jobId: string; result: Result; selection: Selection }) {
  const source = useSource(jobId, true);
  const target = useRef<HTMLTableCellElement>(null);

  // The cell to highlight: an explicit one, or the selected value's own cell.
  const cell = useMemo(() => {
    if (selection.cell) return selection.cell;
    const row = result.rows.find((r) => r.source_row === selection.row);
    return (selection.field && row?.fields[selection.field]?.source?.cell) || null;
  }, [selection, result.rows]);
  const highlightRow = selection.row;
  const headerRows = new Set(result.source.header_rows);

  useEffect(() => {
    target.current?.scrollIntoView({ block: "center", inline: "center" });
  }, [cell, source.data]);

  if (source.isLoading) return <Empty>Loading the original file…</Empty>;
  if (source.error) return <div className="p-4"><ErrorNote error={source.error} /></div>;
  const data = source.data!;
  const width = Math.max(0, ...data.rows.map((r) => r.length));
  const rows = data.rows.slice(0, MAX_RENDER_ROWS);

  return (
    <div>
      <p className="px-4 py-2.5 text-sm text-ink-2">
        Sheet {data.sheet}, unchanged. {cell ? `Showing cell ${cell}.` : "Select a value to see where it came from."}
      </p>
      <div className="max-h-[36rem] overflow-auto border-t border-rule-soft">
        <table className="border-separate border-spacing-0 text-xs">
          <thead className="sticky top-0 z-10 bg-paper">
            <tr>
              <th className="sticky left-0 z-20 border-b border-r border-rule bg-paper px-2 py-1" />
              {Array.from({ length: width }, (_, c) => (
                <th key={c} className="border-b border-r border-rule px-2 py-1 font-medium text-ink-3">
                  {colLetter(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const rowNo = i + 1;
              return (
                <tr key={i} className={headerRows.has(rowNo) ? "bg-rule-soft font-semibold" : rowNo === highlightRow ? "bg-action/5" : ""}>
                  <th className="sticky left-0 border-b border-r border-rule bg-paper px-2 py-1 text-right font-medium text-ink-3">
                    {rowNo}
                  </th>
                  {Array.from({ length: width }, (_, c) => {
                    const address = `${colLetter(c)}${rowNo}`;
                    const hit = address === cell;
                    return (
                      <td
                        key={c}
                        ref={hit ? target : undefined}
                        className={`max-w-[16rem] truncate whitespace-nowrap border-b border-r border-rule-soft px-2 py-1 ${
                          hit ? "bg-warn-soft outline outline-2 -outline-offset-2 outline-warn" : ""
                        }`}
                        title={r[c] ?? undefined}
                      >
                        {r[c] ?? ""}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {(data.truncated || data.rows.length > MAX_RENDER_ROWS) && (
          <p className="px-4 py-2 text-sm text-ink-3">Only the first {MAX_RENDER_ROWS} rows are shown here.</p>
        )}
      </div>
    </div>
  );
}
