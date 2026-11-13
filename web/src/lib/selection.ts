import type { Issue, Result, Row } from "./types";

export interface Selection {
  row: number | null; // source_row
  field: string | null;
  cell?: string | null; // a source cell to highlight, e.g. "F8"
}

export const NONE: Selection = { row: null, field: null };

export function rowLabel(row: Row): string {
  const unit = row.fields.unit?.value;
  return unit ? `Unit ${unit}` : `Row ${row.source_row}`;
}

/** Open issues by source row, for marking units and cells. */
export function issuesByRow(result: Result): Map<number, Issue[]> {
  const map = new Map<number, Issue[]>();
  for (const i of result.issues) {
    if (i.row === null || i.acknowledgment || i.severity === "info") continue;
    const list = map.get(i.row) ?? [];
    list.push(i);
    map.set(i.row, list);
  }
  return map;
}

export function worstSeverity(issues: Issue[] | undefined): "error" | "warning" | null {
  if (!issues?.length) return null;
  return issues.some((i) => i.severity === "error") ? "error" : "warning";
}

/** Column letter for a 0-based index: 0 -> A, 26 -> AA. */
export function colLetter(i: number): string {
  let s = "";
  let n = i + 1;
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}
