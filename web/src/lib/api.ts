import type { AnyJobResponse, ExportFormat, FieldInfo, Job, JobResponse, SourceSheet } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const USER_KEY = "tieout.reviewer";

export function reviewerName(): string {
  try {
    return localStorage.getItem(USER_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setReviewerName(name: string): void {
  try {
    localStorage.setItem(USER_KEY, name);
  } catch {
    /* storage can be unavailable (private mode); the name just isn't remembered */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const user = reviewerName();
  if (user) headers.set("X-Tieout-User", user);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  fields: () => request<FieldInfo[]>("/api/fields"),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<AnyJobResponse>(`/api/jobs/${id}`),
  upload: (file: File, asOf?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (asOf) form.append("as_of", asOf);
    return request<AnyJobResponse>("/api/jobs", { method: "POST", body: form });
  },
  remove: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  settings: (id: string, settings: { sheet?: string | null; as_of?: string | null }) =>
    request<JobResponse>(`/api/jobs/${id}/settings`, { method: "PUT", body: json(settings) }),
  source: (id: string) => request<SourceSheet>(`/api/jobs/${id}/source`),
  setMapping: (id: string, header: string, field: string | null) =>
    request<JobResponse>(`/api/jobs/${id}/mapping`, { method: "PUT", body: json({ header, field }) }),
  resetMapping: (id: string, header: string) =>
    request<JobResponse>(`/api/jobs/${id}/mapping/reset`, { method: "POST", body: json({ header, field: null }) }),
  correct: (id: string, c: { source_row: number; field: string; value: string | null; reason: string }) =>
    request<JobResponse>(`/api/jobs/${id}/corrections`, { method: "POST", body: json(c) }),
  removeCorrection: (id: string, sourceRow: number, field: string) =>
    request<JobResponse>(
      `/api/jobs/${id}/corrections?source_row=${sourceRow}&field=${encodeURIComponent(field)}`,
      { method: "DELETE" },
    ),
  acknowledge: (id: string, issueId: string, note: string) =>
    request<JobResponse>(`/api/jobs/${id}/acknowledgments`, { method: "POST", body: json({ issue_id: issueId, note }) }),
  unacknowledge: (id: string, issueId: string) =>
    request<JobResponse>(`/api/jobs/${id}/acknowledgments/${issueId}`, { method: "DELETE" }),
  saveTemplate: (id: string, name: string) =>
    request<{ template: string }>(`/api/jobs/${id}/template`, { method: "POST", body: json({ name }) }),
  exportUrl: (id: string, fmt: ExportFormat, redactTenants = false) =>
    `/api/jobs/${id}/export/${fmt}${redactTenants ? "?redact_tenants=true" : ""}`,
};
