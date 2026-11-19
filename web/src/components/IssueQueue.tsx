import { useState } from "react";
import { api } from "../lib/api";
import { ruleLabel } from "../lib/format";
import { useJobAction } from "../lib/hooks";
import type { Issue, Result } from "../lib/types";
import { Button, Empty, ErrorNote, SeverityMark } from "./ui";

type Filter = "open" | "accepted" | "all";

const QUIET_RULES = new Set(["total_ties_out"]);

export function IssueQueue({
  jobId,
  result,
  onSelect,
}: {
  jobId: string;
  result: Result;
  onSelect: (row: number | null, field: string | null) => void;
}) {
  const [filter, setFilter] = useState<Filter>("open");
  const visible = result.issues.filter((i) => !QUIET_RULES.has(i.rule));
  const counts = {
    open: visible.filter((i) => !i.acknowledgment && i.severity !== "info").length,
    accepted: visible.filter((i) => i.acknowledgment).length,
    all: visible.length,
  };
  const shown = visible.filter((i) =>
    filter === "open" ? !i.acknowledgment && i.severity !== "info" : filter === "accepted" ? i.acknowledgment : true,
  );

  return (
    <section aria-label="Issues" className="flex min-w-0 flex-col rounded-md border border-rule bg-surface xl:max-h-[32rem]">
      <div className="flex items-center gap-1 border-b border-rule-soft px-3 py-2">
        <h2 className="mr-auto pl-1 text-sm font-semibold">To review</h2>
        {(["open", "accepted", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
            className={`rounded px-2 py-1 text-xs font-medium ${filter === f ? "bg-ink text-white" : "text-ink-2 hover:bg-paper"}`}
          >
            {f === "open" ? "Open" : f === "accepted" ? "Accepted" : "All"} {counts[f]}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <Empty>
          {filter === "open"
            ? "Nothing left to review. Every total ties out and no unit has an open problem."
            : "No issues here."}
        </Empty>
      ) : (
        <ul className="divide-y divide-rule-soft overflow-y-auto">
          {shown.map((issue) => (
            <IssueItem key={issue.id} jobId={jobId} issue={issue} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function IssueItem({
  jobId,
  issue,
  onSelect,
}: {
  jobId: string;
  issue: Issue;
  onSelect?: (row: number | null, field: string | null) => void;
}) {
  const [accepting, setAccepting] = useState(false);
  const [note, setNote] = useState("");
  const accept = useJobAction(jobId, (n: string) => api.acknowledge(jobId, issue.id, n));
  const reopen = useJobAction(jobId, () => api.unacknowledge(jobId, issue.id));
  const acked = issue.acknowledgment;

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-start gap-2.5">
        <span className="mt-1.5">
          <SeverityMark severity={issue.severity} muted={!!acked} />
        </span>
        <div className="min-w-0 flex-1">
          <button
            onClick={() => onSelect?.(issue.row, issue.field)}
            className="block w-full text-left"
            disabled={!onSelect}
          >
            <span className={`text-sm font-medium ${acked ? "text-ink-3" : ""}`}>{ruleLabel(issue.rule)}</span>
            {issue.row !== null && <span className="ml-2 text-xs text-ink-3">row {issue.row}</span>}
            <span className={`block text-sm ${acked ? "text-ink-3" : "text-ink-2"}`}>{issue.message}</span>
          </button>
          {acked ? (
            <p className="mt-1 text-xs text-ink-3">
              Accepted{acked.author ? ` by ${acked.author}` : ""}: “{acked.note}”{" "}
              <Button variant="quiet" className="text-xs" onClick={() => reopen.mutate(undefined)}>
                Reopen
              </Button>
            </p>
          ) : issue.severity !== "info" && !accepting ? (
            <Button variant="quiet" className="mt-1 text-xs" onClick={() => setAccepting(true)}>
              Accept as is
            </Button>
          ) : null}
          {accepting && !acked && (
            <form
              className="mt-2 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (note.trim()) accept.mutate(note.trim(), { onSuccess: () => setAccepting(false) });
              }}
            >
              <input
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this is fine, e.g. confirmed with the property manager"
                aria-label="Reason for accepting"
                maxLength={500}
                className="min-w-0 flex-1 rounded border border-rule px-2 py-1 text-sm"
              />
              <Button type="submit" variant="primary" disabled={!note.trim() || accept.isPending}>
                Accept
              </Button>
              <Button onClick={() => setAccepting(false)}>Cancel</Button>
            </form>
          )}
          <ErrorNote error={accept.error ?? reopen.error} />
        </div>
      </div>
    </li>
  );
}
