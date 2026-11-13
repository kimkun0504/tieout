import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useJob, useJobAction } from "../lib/hooks";
import { go } from "../lib/route";
import { NONE, type Selection } from "../lib/selection";
import type { ExportFormat, JobResponse, T12Response } from "../lib/types";
import { AuditLog } from "./AuditLog";
import { Inspector } from "./Inspector";
import { IssueQueue } from "./IssueQueue";
import { Check } from "./JobsPage";
import { MappingTable } from "./MappingTable";
import { Metrics } from "./Metrics";
import { SourceView } from "./SourceView";
import { T12View } from "./T12View";
import { StackingPlan } from "./StackingPlan";
import { TieOutStrip } from "./TieOutStrip";
import { Button, Empty, ErrorNote } from "./ui";
import { UnitsTable } from "./UnitsTable";

type Tab = "units" | "mapping" | "source" | "audit";

export function JobView({ id }: { id: string }) {
  const job = useJob(id);
  const [selection, setSelection] = useState<Selection>(NONE);
  const [tab, setTab] = useState<Tab>("units");

  if (job.isLoading) return <Empty>Loading…</Empty>;
  if (job.error || !job.data) {
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-5 py-8">
        <ErrorNote error={job.error ?? new Error("This rent roll could not be loaded.")} />
        <a href="#/" className="text-action hover:underline" onClick={() => go({ page: "jobs" })}>
          Back to all rent rolls
        </a>
      </main>
    );
  }

  if (job.data.result.document_type === "t12") return <T12View data={job.data as T12Response} />;
  const data = job.data as JobResponse;
  const { result } = data;
  return (
    <Review
      id={id}
      data={data}
      selection={selection}
      setSelection={setSelection}
      tab={tab}
      setTab={setTab}
      result={result}
    />
  );
}

function Review({
  id,
  data,
  result,
  selection,
  setSelection,
  tab,
  setTab,
}: {
  id: string;
  data: JobResponse;
  result: JobResponse["result"];
  selection: Selection;
  setSelection: (s: Selection | ((s: Selection) => Selection)) => void;
  tab: Tab;
  setTab: (t: Tab) => void;
}) {
  // Open problems in file order, for stepping through with j / k.
  const problems = useMemo(
    () =>
      result.issues
        .filter((i) => !i.acknowledgment && i.severity !== "info" && i.row !== null)
        .sort((a, b) => (a.row ?? 0) - (b.row ?? 0)),
    [result.issues],
  );
  const step = (dir: 1 | -1) => {
    if (problems.length === 0) return;
    const current = problems.findIndex((i) => i.row === selection.row && i.field === selection.field);
    const after = problems.findIndex((i) => (i.row ?? 0) > (selection.row ?? 0));
    let idx: number;
    if (current >= 0) idx = (current + dir + problems.length) % problems.length;
    else if (dir === 1) idx = after >= 0 ? after : 0;
    else idx = (after > 0 ? after : problems.length) - 1;
    const target = problems[idx]!;
    setSelection({ row: target.row, field: target.field });
    if (result.rows.some((r) => r.source_row === target.row)) setTab("units");
  };
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) return;
      if (e.key === "j") step(1);
      if (e.key === "k") step(-1);
      if (e.key === "Escape") setSelection(NONE);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const showInSource = (cell: string) => {
    setSelection((s) => ({ ...s, cell }));
    setTab("source");
  };

  return (
    <main className="space-y-4 px-5 py-5">
      <JobHeader data={data} />
      <TieOutStrip result={result} onSelect={(row, field) => setSelection({ row, field })} />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_22rem]">
        <StackingPlan result={result} selection={selection} onSelect={(row) => setSelection({ row, field: null })} />
        <Metrics result={result} />
        <IssueQueue
          jobId={id}
          result={result}
          onSelect={(row, field) => {
            setSelection({ row, field });
            setTab(row === null ? "mapping" : "units");
          }}
        />
      </div>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="min-w-0 rounded-md border border-rule bg-surface">
          <div className="flex items-center border-b border-rule-soft pr-3">
          <div role="tablist" aria-label="Review views" className="flex gap-1 px-3">
            {(
              [
                ["units", `Units (${result.rows.length})`],
                ["mapping", "Column mapping"],
                ["source", "Original file"],
                ["audit", `Changes (${result.review.audit.length})`],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-medium ${
                  tab === key ? "border-action text-ink" : "border-transparent text-ink-3 hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {problems.length > 0 && (
            <div className="ml-auto flex items-center gap-1 text-sm text-ink-2">
              <span className="hidden sm:inline">{problems.length} open</span>
              <Button onClick={() => step(-1)} aria-label="Previous problem" title="Previous problem (k)">
                Previous
              </Button>
              <Button onClick={() => step(1)} aria-label="Next problem" title="Next problem (j)">
                Next problem
              </Button>
            </div>
          )}
          </div>
          <div role="tabpanel">
            {tab === "units" && <UnitsTable result={result} selection={selection} onSelect={setSelection} />}
            {tab === "mapping" && <MappingTable jobId={id} result={result} />}
            {tab === "source" && <SourceView jobId={id} result={result} selection={selection} />}
            {tab === "audit" && <AuditLog result={result} />}
          </div>
        </section>
        <Inspector jobId={id} result={result} selection={selection} onSelect={setSelection} onShowSource={showInSource} />
      </div>
    </main>
  );
}

function JobHeader({ data }: { data: JobResponse }) {
  const { job, result } = data;
  const settings = useJobAction(job.id, (next: { sheet: string | null; as_of: string | null }) =>
    api.settings(job.id, next),
  );
  const s = result.summary;
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0">
        <a href="#/" className="text-sm text-ink-3 hover:text-ink">
          All rent rolls
        </a>
        <h1 className="truncate text-xl font-semibold tracking-tight">{job.filename}</h1>
        <p className="text-sm text-ink-3">
          Sheet {result.source.sheet}, header on row {result.source.header_rows.join(" and ")}
        </p>
      </div>
      <div className="flex items-center gap-2" aria-live="polite">
        {result.ok ? (
          <span className="inline-flex items-center gap-1.5 rounded bg-tie-soft px-2.5 py-1 font-semibold text-tie">
            <Check /> Ready to export
          </span>
        ) : (
          <span className="rounded bg-err-soft px-2.5 py-1 font-semibold text-err">
            {s.errors} {s.errors === 1 ? "error" : "errors"} to resolve
          </span>
        )}
        {s.warnings > 0 && <span className="text-sm text-ink-2">{s.warnings} to check</span>}
      </div>
      {settings.error && (
        <div className="basis-full">
          <ErrorNote error={settings.error} />
        </div>
      )}
      <div className="ml-auto flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm text-ink-2">
          Report date
          <input
            key={job.as_of ?? ""}
            type="date"
            defaultValue={job.as_of ?? ""}
            onBlur={(e) => {
              const v = e.target.value || null;
              if (v !== job.as_of) settings.mutate({ sheet: job.sheet, as_of: v });
            }}
            className="rounded border border-rule bg-surface px-2 py-1 text-ink"
          />
        </label>
        {result.source.sheets.length > 1 && (
          <label className="flex flex-col text-sm text-ink-2">
            Sheet
            <select
              value={result.source.sheet}
              onChange={(e) => settings.mutate({ sheet: e.target.value, as_of: job.as_of })}
              className="rounded border border-rule bg-surface px-2 py-1 text-ink"
            >
              {result.source.sheets.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
        <ExportMenu jobId={job.id} ok={result.ok} />
      </div>
    </div>
  );
}

const EXPORTS: [ExportFormat, string, boolean][] = [
  ["xlsx", "Excel workbook", false],
  ["csv", "CSV", false],
  ["json", "JSON with sources", false],
  ["jsonl", "Records for AI (JSONL)", false],
  ["jsonl", "Records for AI, no tenant names", true],
  ["issues", "Issues (CSV)", false],
  ["report", "Summary report", false],
];

function ExportMenu({ jobId, ok }: { jobId: string; ok: boolean }) {
  return (
    <details className="relative">
      <summary
        className={`cursor-pointer list-none rounded px-3 py-1.5 text-sm font-medium ${
          ok ? "bg-action text-white hover:bg-action-hover" : "border border-rule bg-surface hover:border-ink-3"
        }`}
      >
        Export
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-rule bg-surface py-1 shadow-lg">
        {!ok && <p className="px-3 py-1.5 text-xs text-err">Open errors will be listed in the export.</p>}
        {EXPORTS.map(([fmt, label, redact]) => (
          <a
            key={label}
            href={api.exportUrl(jobId, fmt, redact)}
            download
            className="block px-3 py-1.5 text-sm hover:bg-paper"
          >
            {label}
          </a>
        ))}
      </div>
    </details>
  );
}
