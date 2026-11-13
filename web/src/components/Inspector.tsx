import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fieldLabel, fmtMoney, fmtTimestamp, fmtValue } from "../lib/format";
import { useJobAction } from "../lib/hooks";
import { rowLabel, type Selection } from "../lib/selection";
import type { FieldInfo, ReportedTotal, Result, Row, TracedValue } from "../lib/types";
import { IssueItem } from "./IssueQueue";
import { Button, ErrorNote } from "./ui";

export function Inspector({
  jobId,
  result,
  selection,
  onSelect,
  onShowSource,
}: {
  jobId: string;
  result: Result;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onShowSource: (cell: string) => void;
}) {
  const row = result.rows.find((r) => r.source_row === selection.row);
  const total = result.totals.find((t) => t.row === selection.row);

  return (
    <aside aria-label="Inspector" className="self-start rounded-md border border-rule bg-surface xl:sticky xl:top-4">
      {row ? (
        <RowInspector jobId={jobId} result={result} row={row} field={selection.field} onSelect={onSelect} onShowSource={onShowSource} />
      ) : total ? (
        <TotalInspector jobId={jobId} result={result} total={total} />
      ) : (
        <div className="px-4 py-6 text-sm text-ink-2">
          <p className="font-medium text-ink">Select a unit or a value</p>
          <p className="mt-1">
            You'll see the cell it was read from, how tieout interpreted it, and any problem with it. You can correct a
            value here; the original file is never changed.
          </p>
        </div>
      )}
    </aside>
  );
}

function RowInspector({
  jobId,
  result,
  row,
  field,
  onSelect,
  onShowSource,
}: {
  jobId: string;
  result: Result;
  row: Row;
  field: string | null;
  onSelect: (s: Selection) => void;
  onShowSource: (cell: string) => void;
}) {
  const issues = result.issues.filter((i) => i.row === row.source_row && i.severity !== "info");
  const fields = result.fields.filter((f) => row.fields[f.name] !== undefined || f.name === field);
  return (
    <div>
      <div className="border-b border-rule-soft px-4 py-3">
        <h2 className="text-base font-semibold">{rowLabel(row)}</h2>
        <p className="text-sm text-ink-3">
          Row {row.source_row} of {result.source.file}
          {row.section ? `, ${row.section}` : ""}
        </p>
      </div>
      {issues.length > 0 && (
        <ul className="divide-y divide-rule-soft border-b border-rule-soft bg-paper/60">
          {issues.map((i) => (
            <IssueItem key={i.id} jobId={jobId} issue={i} onSelect={(_, f) => onSelect({ row: row.source_row, field: f })} />
          ))}
        </ul>
      )}
      <dl className="divide-y divide-rule-soft">
        {fields.map((f) => (
          <FieldDetail
            key={f.name}
            jobId={jobId}
            row={row}
            field={f}
            tv={row.fields[f.name]}
            open={f.name === field}
            onOpen={() => onSelect({ row: row.source_row, field: f.name === field ? null : f.name })}
            onShowSource={onShowSource}
          />
        ))}
      </dl>
      {row.charges.length > 0 && (
        <div className="border-t border-rule px-4 py-3">
          <h3 className="text-sm font-semibold">Charge lines</h3>
          <table className="mt-1 w-full text-sm">
            <tbody>
              {row.charges.map((c, i) => (
                <tr key={i} className="border-t border-rule-soft first:border-0">
                  <td className="py-1">{c.code.value ?? "(no code)"}</td>
                  <td className="py-1 text-ink-3">{c.category}</td>
                  <td className="py-1 text-right">{fmtMoney(c.amount.value) || c.amount.issue}</td>
                  <td className="py-1 pl-2 text-right">
                    {c.amount.source && (
                      <Button variant="quiet" className="text-xs" onClick={() => onShowSource(c.amount.source!.cell)}>
                        {c.amount.source.cell}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FieldDetail({
  jobId,
  row,
  field,
  tv,
  open,
  onOpen,
  onShowSource,
}: {
  jobId: string;
  row: Row;
  field: FieldInfo;
  tv: TracedValue | undefined;
  open: boolean;
  onOpen: () => void;
  onShowSource: (cell: string) => void;
}) {
  const shown = tv ? fmtValue(tv.value, field.type) : "";
  return (
    <div className={open ? "bg-action/5" : ""}>
      <button onClick={onOpen} aria-expanded={open} className="flex w-full items-baseline gap-3 px-4 py-2 text-left hover:bg-paper">
        <dt className="w-28 shrink-0 text-sm text-ink-2">{fieldLabel(field.name)}</dt>
        <dd className={`min-w-0 flex-1 truncate text-sm ${field.type === "money" || field.type === "number" ? "text-right" : ""}`}>
          {shown || <span className="text-ink-3">{tv?.issue ? "Couldn't read" : "Empty"}</span>}
        </dd>
        <span className="w-14 shrink-0 text-right text-xs text-ink-3">
          {tv?.correction ? "corrected" : tv?.derived ? "filled" : tv?.source?.cell ?? ""}
        </span>
      </button>
      {open && (
        <div className="space-y-2 px-4 pb-3 text-sm">
          <Provenance tv={tv} type={field.type} onShowSource={onShowSource} />
          {field.output !== false && <CorrectionForm jobId={jobId} row={row} field={field} tv={tv} />}
        </div>
      )}
    </div>
  );
}

function Provenance({
  tv,
  type,
  onShowSource,
}: {
  tv: TracedValue | undefined;
  type: FieldInfo["type"];
  onShowSource: (cell: string) => void;
}) {
  if (!tv) return <p className="text-ink-3">This file has no column for this field.</p>;
  const cells = tv.sources?.length ? tv.sources : tv.source ? [tv.source] : [];
  return (
    <div className="space-y-1 rounded border border-rule-soft bg-surface px-3 py-2">
      {tv.raw !== null && tv.raw !== undefined && (
        <p>
          <span className="text-ink-3">In the file: </span>
          <span className="whitespace-pre-wrap rounded bg-paper px-1">{String(tv.raw)}</span>
        </p>
      )}
      {tv.derived && !tv.correction && (
        <p className="text-ink-2">
          {cells.length > 1 ? `Added up from ${cells.length} cells.` : "Worked out by tieout, not read directly."}
        </p>
      )}
      {cells.length > 0 && (
        <p className="flex flex-wrap items-center gap-x-2">
          <span className="text-ink-3">{cells.length > 1 ? "Cells:" : "Cell:"}</span>
          {cells.map((c) => (
            <Button key={c.cell} variant="quiet" onClick={() => onShowSource(c.cell)}>
              {c.sheet}!{c.cell}
            </Button>
          ))}
        </p>
      )}
      {tv.issue && <p className="text-err">{tv.issue}</p>}
      {tv.correction && (
        <p className="text-ink-2">
          Was {fmtValue(tv.original ?? null, type) || "empty"}. Corrected
          {tv.correction.author ? ` by ${tv.correction.author}` : ""} {fmtTimestamp(tv.correction.at)}: “{tv.correction.reason}”
        </p>
      )}
    </div>
  );
}

function CorrectionForm({ jobId, row, field, tv }: { jobId: string; row: Row; field: FieldInfo; tv: TracedValue | undefined }) {
  const initial = tv?.correction?.value ?? (tv?.value === null || tv?.value === undefined ? "" : String(tv.value));
  const [value, setValue] = useState(initial);
  const [reason, setReason] = useState("");
  useEffect(() => {
    setValue(initial);
    setReason("");
  }, [initial, row.source_row, field.name]);

  const save = useJobAction(jobId, () =>
    api.correct(jobId, { source_row: row.source_row, field: field.name, value: value.trim() || null, reason: reason.trim() }),
  );
  const undo = useJobAction(jobId, () => api.removeCorrection(jobId, row.source_row, field.name));
  const placeholder =
    field.type === "date" ? "MM/DD/YYYY" : field.type === "money" ? "1,250.00" : field.type === "status" ? "occupied, vacant, notice…" : "";

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <label className="block">
        <span className="text-ink-2">Correct value</span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          className="mt-0.5 w-full rounded border border-rule px-2 py-1"
        />
      </label>
      <label className="block">
        <span className="text-ink-2">Reason</span>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Lease amendment dated 10/15"
          maxLength={500}
          className="mt-0.5 w-full rounded border border-rule px-2 py-1"
        />
      </label>
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={!reason.trim() || save.isPending}>
          Save correction
        </Button>
        {tv?.correction && (
          <Button variant="danger" onClick={() => undo.mutate(undefined)} disabled={undo.isPending}>
            Undo correction
          </Button>
        )}
      </div>
      <ErrorNote error={save.error ?? undo.error} />
    </form>
  );
}

function TotalInspector({ jobId, result, total }: { jobId: string; result: Result; total: ReportedTotal }) {
  const issues = result.issues.filter((i) => i.row === total.row && i.severity !== "info");
  return (
    <div>
      <div className="border-b border-rule-soft px-4 py-3">
        <h2 className="text-base font-semibold">{total.label}</h2>
        <p className="text-sm text-ink-3">
          Row {total.row}, covers {total.covers_rows.length} units
        </p>
      </div>
      <table className="w-full text-sm">
        <thead className="text-ink-3">
          <tr>
            <th className="px-4 py-1.5 text-left font-medium">Field</th>
            <th className="px-2 py-1.5 text-right font-medium">Reported</th>
            <th className="px-4 py-1.5 text-right font-medium">Units add to</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(total.amounts).map(([f, tv]) => (
            <tr key={f} className="border-t border-rule-soft">
              <td className="px-4 py-1.5">{fieldLabel(f)}</td>
              <td className="px-2 py-1.5 text-right">{f === "sqft" ? tv.value : fmtMoney(tv.value)}</td>
              <td className="px-4 py-1.5 text-right">{f === "sqft" ? total.computed[f] : fmtMoney(total.computed[f] ?? null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {issues.length > 0 && (
        <ul className="divide-y divide-rule-soft border-t border-rule">
          {issues.map((i) => (
            <IssueItem key={i.id} jobId={jobId} issue={i} />
          ))}
        </ul>
      )}
      <p className="border-t border-rule-soft px-4 py-2.5 text-xs text-ink-3">
        If a unit's value was misread, correct that unit and this total will be checked again. If the file's own total
        is wrong, accept the issue with a note.
      </p>
    </div>
  );
}
