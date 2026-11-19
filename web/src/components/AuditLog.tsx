import { fieldLabel, fmtTimestamp } from "../lib/format";
import type { AuditEvent, Result } from "../lib/types";
import { Empty } from "./ui";

function describe(e: AuditEvent): string {
  const d = e.detail as Record<string, string | number | null>;
  switch (e.action) {
    case "correct":
      return `Corrected ${fieldLabel(String(d.field)).toLowerCase()} on row ${d.source_row} to “${d.value ?? "empty"}”: ${d.reason}`;
    case "remove_correction":
      return `Undid the ${fieldLabel(String(d.field)).toLowerCase()} correction on row ${d.source_row}`;
    case "override_mapping":
      return `Read column “${d.header}” as ${fieldLabel(d.field as string | null).toLowerCase()}`;
    case "clear_mapping_override":
      return `Went back to automatic mapping for column “${d.header}”`;
    case "acknowledge":
      return `Accepted an issue: ${d.note}`;
    case "unacknowledge":
      return "Reopened an issue";
    default:
      return e.action;
  }
}

export function AuditLog({ result }: { result: Result }) {
  const events = [...result.review.audit].reverse();
  if (events.length === 0) return <Empty>No changes yet. Corrections, accepted issues and mapping changes appear here.</Empty>;
  return (
    <ol className="divide-y divide-rule-soft">
      {events.map((e, i) => (
        <li key={i} className="flex gap-4 px-4 py-2.5 text-sm">
          <time dateTime={e.at} className="w-36 shrink-0 text-ink-3">
            {fmtTimestamp(e.at)}
          </time>
          <span className="w-24 shrink-0 truncate text-ink-2">{e.author || "reviewer"}</span>
          <span className="min-w-0">{describe(e)}</span>
        </li>
      ))}
    </ol>
  );
}
