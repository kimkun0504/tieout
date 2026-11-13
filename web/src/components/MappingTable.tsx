import { useState } from "react";
import { api } from "../lib/api";
import { fieldLabel } from "../lib/format";
import { useFields, useJobAction } from "../lib/hooks";
import { colLetter } from "../lib/selection";
import type { Mapping, Result } from "../lib/types";
import { Button, ErrorNote } from "./ui";

const METHOD_LABEL: Record<Mapping["method"], string> = {
  template: "Saved template",
  synonym: "Matched by name",
  mapper: "Suggested",
  override: "Set by you",
  unmapped: "",
};

export function MappingTable({ jobId, result }: { jobId: string; result: Result }) {
  const fields = useFields();
  const setMapping = useJobAction(jobId, ({ header, field }: { header: string; field: string | null }) =>
    api.setMapping(jobId, header, field),
  );
  const reset = useJobAction(jobId, (header: string) => api.resetMapping(jobId, header));
  const overrides = result.review.mapping_overrides;

  return (
    <div>
      <p className="max-w-3xl px-4 py-3 text-sm text-ink-2">
        How each column in the file is read. Change a column and every unit is re-read and checked again. Changes apply
        to this file only; save them as a template to reuse them for every file with the same columns.
      </p>
      <div className="overflow-x-auto border-t border-rule-soft">
        <table className="w-full text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-rule-soft">
              <th className="px-4 py-2 font-medium">Column</th>
              <th className="px-4 py-2 font-medium">Header in file</th>
              <th className="px-4 py-2 font-medium">Read as</th>
              <th className="px-4 py-2 font-medium">How</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {result.mappings.map((m) => {
              const weak = m.field && m.confidence < 0.9;
              return (
                <tr key={m.column} className="border-b border-rule-soft last:border-0">
                  <td className="px-4 py-2 text-ink-3">{colLetter(m.column - 1)}</td>
                  <td className="px-4 py-2 font-medium">{m.header}</td>
                  <td className="px-4 py-2">
                    <select
                      value={m.field ?? ""}
                      aria-label={`Field for column ${m.header}`}
                      onChange={(e) => setMapping.mutate({ header: m.header, field: e.target.value || null })}
                      className={`rounded border px-2 py-1 ${weak ? "border-warn" : "border-rule"} ${m.field ? "" : "text-ink-3"}`}
                    >
                      <option value="">Not used</option>
                      {(fields.data ?? []).map((f) => (
                        <option key={f.name} value={f.name}>
                          {fieldLabel(f.name)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-2 text-ink-2">
                    {METHOD_LABEL[m.method]}
                    {weak && <span className="ml-1 text-warn">({Math.round(m.confidence * 100)}% sure)</span>}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {m.header in overrides && (
                      <Button variant="quiet" onClick={() => reset.mutate(m.header)}>
                        Use automatic
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="space-y-2 border-t border-rule-soft px-4 py-3">
        <ErrorNote error={setMapping.error ?? reset.error} />
        <SaveTemplate jobId={jobId} />
      </div>
    </div>
  );
}

function SaveTemplate({ jobId }: { jobId: string }) {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await api.saveTemplate(jobId, name.trim());
          setSaved(name.trim());
          setName("");
        } catch (err) {
          setError(err);
        }
      }}
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Template name, e.g. Yardi rent roll export"
        aria-label="Template name"
        maxLength={100}
        className="w-72 rounded border border-rule px-2 py-1 text-sm"
      />
      <Button type="submit" disabled={!name.trim()}>
        Save as template
      </Button>
      {saved && <span className="text-sm text-tie">Saved “{saved}”. Files with these columns will use it.</span>}
      <ErrorNote error={error} />
    </form>
  );
}
