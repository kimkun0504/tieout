import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtBytes, fmtMoney, fmtPct, fmtTimestamp } from "../lib/format";
import { jobKey } from "../lib/hooks";
import { go } from "../lib/route";
import type { Job } from "../lib/types";
import { Button, Empty, ErrorNote, Panel } from "./ui";

const ACCEPT = ".xlsx,.xlsm,.xls,.csv,.tsv,.txt,.pdf";

export function JobsPage() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs });
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-5 py-8">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Check a rent roll or T-12</h1>
        <p className="mt-1 text-ink-2">
          Upload an export from any property management system. tieout maps its columns, cleans every value, and checks
          that every subtotal and total adds up to what it covers. Operating statements are recognised automatically.
        </p>
      </div>
      <Upload />
      <Panel title="Files">
        {jobs.isLoading ? (
          <Empty>Loading…</Empty>
        ) : jobs.error ? (
          <div className="p-4">
            <ErrorNote error={jobs.error} />
          </div>
        ) : jobs.data && jobs.data.length > 0 ? (
          <JobsTable jobs={jobs.data} />
        ) : (
          <Empty>No files yet. Upload a rent roll or T-12 above to start a review.</Empty>
        )}
      </Panel>
    </main>
  );
}

type Queued = { name: string; state: "waiting" | "reading" | "done" | "failed"; job?: Job; error?: string };

function Upload() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [asOf, setAsOf] = useState("");
  const [dragging, setDragging] = useState(false);
  const [queue, setQueue] = useState<Queued[]>([]);
  const busy = queue.some((q) => q.state === "waiting" || q.state === "reading");

  const pick = async (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (files.length === 0 || busy) return;
    setQueue(files.map((f) => ({ name: f.name, state: "waiting" })));
    const set = (i: number, patch: Partial<Queued>) =>
      setQueue((q) => q.map((item, k) => (k === i ? { ...item, ...patch } : item)));
    // One at a time: the server reads each file fully, and order stays predictable.
    for (const [i, file] of files.entries()) {
      set(i, { state: "reading" });
      try {
        const data = await api.upload(file, asOf || undefined);
        qc.setQueryData(jobKey(data.job.id), data);
        set(i, { state: "done", job: data.job });
        if (files.length === 1) {
          setQueue([]);
          go({ page: "job", id: data.job.id });
        }
      } catch (e) {
        set(i, { state: "failed", error: e instanceof Error ? e.message : String(e) });
      }
    }
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };

  const done = queue.filter((q) => q.state === "done" || q.state === "failed").length;
  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void pick(e.dataTransfer.files);
        }}
        className={`flex flex-wrap items-center gap-x-6 gap-y-3 rounded-md border-2 border-dashed px-5 py-6 transition-colors ${
          dragging ? "border-action bg-action/5" : "border-rule bg-surface"
        }`}
      >
        <div className="min-w-0 flex-1">
          <p className="font-medium" aria-live="polite">
            {busy
              ? `Reading ${queue.length > 1 ? `file ${done + 1} of ${queue.length}` : "the file"}…`
              : "Drop rent rolls or T-12s here: Excel, CSV or PDF"}
          </p>
          <p className="text-sm text-ink-3">
            One file or a whole folder's worth. Up to 25 MB each. PDFs need a text layer (not a scan). Originals are
            never changed.
          </p>
        </div>
        <label className="flex flex-col text-sm text-ink-2">
          Report date
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            aria-describedby="upload-date-hint"
            className="rounded border border-rule px-2 py-1"
          />
          <span id="upload-date-hint" className="text-xs text-ink-3">
            Optional when the file states one
          </span>
        </label>
        <Button variant="primary" onClick={() => input.current?.click()} disabled={busy}>
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          aria-label="Rent roll or T-12 files"
          onChange={(e) => {
            void pick(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {queue.length > 1 && (
        <ul className="divide-y divide-rule-soft rounded-md border border-rule bg-surface text-sm" aria-label="Uploads">
          {queue.map((q, i) => (
            <li key={`${i}-${q.name}`} className="flex items-baseline gap-3 px-4 py-2">
              {q.job ? (
                <a href={`#/jobs/${q.job.id}`} className="font-medium text-action hover:underline">
                  {q.name}
                </a>
              ) : (
                <span className="font-medium">{q.name}</span>
              )}
              <span
                className={`ml-auto ${q.state === "failed" ? "text-err" : q.state === "done" ? "text-tie" : "text-ink-3"}`}
              >
                {q.state === "waiting"
                  ? "Waiting"
                  : q.state === "reading"
                    ? "Reading…"
                    : q.state === "done" && q.job
                      ? <ResultBadge job={q.job} />
                      : q.error}
              </span>
            </li>
          ))}
        </ul>
      )}
      {queue.length === 1 && queue[0]?.state === "failed" && <ErrorNote error={new Error(queue[0].error)} />}
    </div>
  );
}

function JobsTable({ jobs }: { jobs: Job[] }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: api.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  // The same bytes uploaded twice: two reviews of one file can drift apart.
  const firstBySha = new Map<string, Job>();
  for (const j of [...jobs].sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at))) {
    if (j.sha256 && !firstBySha.has(j.sha256)) firstBySha.set(j.sha256, j);
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-rule-soft">
            <th className="px-4 py-2 font-medium">File</th>
            <th className="px-4 py-2 font-medium">Result</th>
            <th className="px-4 py-2 text-right font-medium">Units</th>
            <th className="px-4 py-2 text-right font-medium">Occupancy or period</th>
            <th className="px-4 py-2 text-right font-medium">Rent or NOI</th>
            <th className="px-4 py-2 font-medium">Uploaded</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className="border-b border-rule-soft last:border-0 hover:bg-paper">
              <td className="px-4 py-2.5">
                <a href={`#/jobs/${j.id}`} className="font-medium text-action hover:underline">
                  {j.filename}
                </a>
                <span className="ml-2 text-ink-3">{fmtBytes(j.size)}</span>
                <DuplicateNote job={j} first={firstBySha.get(j.sha256)} />
              </td>
              <td className="px-4 py-2.5">
                <ResultBadge job={j} />
              </td>
              {j.document_type === "t12" ? (
                <>
                  <td className="px-4 py-2.5 text-right text-ink-2">T-12</td>
                  <td className="px-4 py-2.5 text-right text-ink-2">{(j.last_summary as { period?: string }).period ?? ""}</td>
                  <td className="px-4 py-2.5 text-right">
                    {fmtMoney((j.last_summary as { noi?: string }).noi ?? null)}
                    <span className="ml-1 text-xs text-ink-3">NOI</span>
                  </td>
                </>
              ) : (
                <>
                  <td className="px-4 py-2.5 text-right">{j.last_summary.units ?? ""}</td>
                  <td className="px-4 py-2.5 text-right">{fmtPct(j.last_summary.physical_occupancy)}</td>
                  <td className="px-4 py-2.5 text-right">{fmtMoney(j.last_summary.total_current_rent ?? null)}</td>
                </>
              )}
              <td className="px-4 py-2.5 text-ink-2">{fmtTimestamp(j.uploaded_at)}</td>
              <td className="px-4 py-2.5 text-right">
                <Button
                  variant="quiet"
                  className="text-ink-3 hover:text-err"
                  onClick={() => {
                    if (window.confirm(`Delete ${j.filename} and its review? This can't be undone.`)) remove.mutate(j.id);
                  }}
                >
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DuplicateNote({ job, first }: { job: Job; first: Job | undefined }) {
  if (!first || first.id === job.id) return null;
  return (
    <div className="text-xs text-warn">
      Same file as the upload of {first.filename} on {fmtTimestamp(first.uploaded_at)}
    </div>
  );
}

export function ResultBadge({ job }: { job: Pick<Job, "last_ok" | "last_summary"> }) {
  if (job.last_ok === null) return <span className="text-ink-3">Not run</span>;
  const errors = job.last_summary.errors ?? 0;
  const warnings = job.last_summary.warnings ?? 0;
  if (job.last_ok) {
    return (
      <span className="inline-flex items-center gap-1.5 font-medium text-tie">
        <Check />
        <span>
          Ties out{warnings ? <span className="font-normal text-ink-3">, {warnings} to check</span> : null}
        </span>
      </span>
    );
  }
  return (
    <span className="font-medium text-err">
      {errors} {errors === 1 ? "error" : "errors"}
      {warnings ? <span className="font-normal text-ink-3">, {warnings} to check</span> : null}
    </span>
  );
}

export function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 8.5l3 3L13 4.5" stroke="currentColor" strokeWidth="2.2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
