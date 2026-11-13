import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtBytes, fmtMoney, fmtPct, fmtTimestamp } from "../lib/format";
import { jobKey } from "../lib/hooks";
import { go } from "../lib/route";
import type { Job } from "../lib/types";
import { Button, Empty, ErrorNote, Panel } from "./ui";

const ACCEPT = ".xlsx,.xlsm,.csv,.tsv,.txt,.pdf";

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

function Upload() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [asOf, setAsOf] = useState("");
  const [dragging, setDragging] = useState(false);
  const upload = useMutation({
    mutationFn: (file: File) => api.upload(file, asOf || undefined),
    onSuccess: (data) => {
      qc.setQueryData(jobKey(data.job.id), data);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      go({ page: "job", id: data.job.id });
    },
  });

  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (file) upload.mutate(file);
  };

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
          pick(e.dataTransfer.files);
        }}
        className={`flex flex-wrap items-center gap-x-6 gap-y-3 rounded-md border-2 border-dashed px-5 py-6 transition-colors ${
          dragging ? "border-action bg-action/5" : "border-rule bg-surface"
        }`}
      >
        <div className="min-w-0 flex-1">
          <p className="font-medium">{upload.isPending ? "Reading the file…" : "Drop a rent roll or T-12 here: Excel, CSV or PDF"}</p>
          <p className="text-sm text-ink-3">Up to 25 MB. PDFs need a text layer (not a scan). The original file is never changed.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Report date
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            className="rounded border border-rule px-2 py-1"
          />
        </label>
        <Button variant="primary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          Choose file
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          aria-label="Rent roll file"
          onChange={(e) => {
            pick(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      <ErrorNote error={upload.error} />
    </div>
  );
}

function JobsTable({ jobs }: { jobs: Job[] }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: api.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
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
