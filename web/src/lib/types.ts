// Mirrors tieout.export.to_payload and tieout.api. Money values are exact decimal strings.

export type Severity = "error" | "warning" | "info";
export type Status = "occupied" | "vacant" | "notice" | "model" | "down";
export type FieldType = "text" | "money" | "number" | "date" | "status";
export type Scalar = string | number | null;

export interface SourceRef {
  file: string;
  sheet: string;
  cell: string;
  row: number;
  col: number;
}

export interface Correction {
  source_row: number;
  field: string;
  value: string | null;
  reason: string;
  author: string;
  at: string;
}

export interface Acknowledgment {
  issue_id: string;
  note: string;
  author: string;
  at: string;
}

export interface TracedValue {
  value: Scalar;
  raw: Scalar;
  source: SourceRef | null;
  sources?: SourceRef[];
  derived: boolean;
  issue?: string;
  original?: Scalar;
  correction?: Correction;
}

export interface Charge {
  code: TracedValue;
  amount: TracedValue;
  category: "rent" | "concession" | "other";
}

export interface Row {
  source_row: number;
  section: string | null;
  fields: Record<string, TracedValue>;
  charges: Charge[];
}

export interface Issue {
  id: string;
  severity: Severity;
  rule: string;
  message: string;
  row: number | null;
  field: string | null;
  cells: string[];
  acknowledgment: Acknowledgment | null;
}

export interface Mapping {
  column: number;
  header: string;
  field: string | null;
  confidence: number;
  method: "template" | "synonym" | "mapper" | "override" | "unmapped";
  key: string; // override key: header text, or "Rent #2" for a repeated header
}

export interface ReportedTotal {
  row: number;
  label: string;
  section: string | null;
  covers_rows: number[];
  amounts: Record<string, TracedValue>;
  computed: Record<string, string>;
}

export interface FieldInfo {
  name: string;
  type: FieldType;
  description: string;
  required?: boolean;
  output?: boolean;
}

export interface Summary {
  units: number;
  status_counts: Record<string, number>;
  physical_occupancy: number | null;
  total_current_rent: string;
  total_market_rent: string | null;
  total_sqft: number | null;
  errors: number;
  warnings: number;
  acknowledged: number;
  corrections: number;
  future_leases?: number;
}

export interface UnitMix {
  unit_type: string;
  units: number;
  occupied: number;
  occupancy: number | null;
  avg_sqft: number | null;
  avg_market_rent: string | null;
  avg_in_place_rent: string | null;
}

export interface Metrics {
  units: number;
  occupied_units: number;
  vacant_units: number;
  physical_occupancy: number | null;
  economic_occupancy: number | null;
  gross_potential_rent: string | null;
  in_place_rent: string | null;
  loss_to_lease: string | null;
  loss_to_lease_pct: number | null;
  vacancy_loss: string | null;
  concessions: string | null;
  avg_in_place_rent: string | null;
  avg_market_rent: string | null;
  avg_rent_per_sqft: string | null;
  unit_mix: UnitMix[];
  lease_expirations?: {
    as_of: string;
    by_month: { month: string; units: number; rent: string | null }[];
    expired_or_mtm: number;
    no_end_date: number;
    after_12_months: number;
  };
}

export interface AuditEvent {
  at: string;
  author: string;
  action: string;
  detail: Record<string, unknown>;
}

export interface Result {
  document_type?: "rent_roll";
  tieout_version: string;
  source: { file: string; sheet: string; sheets: string[]; header_rows: number[] };
  as_of?: string | null;
  report_date?: { value: string; cell: SourceRef; text: string } | null;
  stated_figures?: StatedFigure[];
  ok: boolean;
  summary: Summary;
  metrics: Metrics;
  fields: FieldInfo[];
  mappings: Mapping[];
  rows: Row[];
  totals: ReportedTotal[];
  issues: Issue[];
  skipped: Record<string, number>;
  review: {
    mapping_overrides: Record<string, string | null>;
    corrections: Correction[];
    acknowledgments: Acknowledgment[];
    audit: AuditEvent[];
  };
}

export interface Job {
  id: string;
  filename: string;
  suffix: string;
  size: number;
  sha256: string;
  uploaded_at: string;
  updated_at: string;
  sheet: string | null;
  as_of: string | null;
  last_summary: Partial<Summary>;
  last_ok: boolean | null;
  document_type?: "rent_roll" | "t12";
}

export interface JobResponse {
  job: Job;
  result: Result;
}

export interface T12Response {
  job: Job;
  result: T12Result;
}

export type AnyJobResponse = JobResponse | T12Response;

export interface SourceSheet {
  sheet: string;
  rows: (string | null)[][];
  truncated: boolean;
  merges: [number, number, number, number][];
}

export type ExportFormat = "xlsx" | "csv" | "json" | "issues" | "report" | "jsonl";

// --- T-12 operating statements (tieout.t12.to_payload) ---------------------------------

export interface T12Line {
  source_row: number;
  code: string | null;
  name: string;
  section: "income" | "expense" | "other" | "below_noi" | "noi";
  kind: "line" | "subtotal" | "noi";
  category: string | null;
  amounts: (string | null)[];
  cells: (string | null)[];
  total: string | null;
  total_cell: string | null;
  month_sum: string;
}

export interface T12Result {
  document_type: "t12";
  tieout_version: string;
  source: { file: string; sheet: string; header_row: number };
  ok: boolean;
  months: string[];
  summary: {
    period: string | null;
    months: number;
    line_items: number;
    total_income: string;
    total_expenses: string;
    noi: string;
    expense_ratio: number | null;
    by_category: Record<string, string>;
    uncategorized: number;
    errors: number;
    warnings: number;
    acknowledged?: number;
  };
  lines: T12Line[];
  issues: Issue[];
}

export interface ComparisonCheck {
  metric: string;
  label: string;
  rent_roll: string | null;
  t12: string | null;
  difference: string | null;
  pct: number | null;
  status: "consistent" | "check" | "investigate" | "unavailable";
  explanation: string;
}

export interface CompareResult {
  rent_roll: { file: string; as_of: string | null };
  t12: { file: string; last_month: string | null };
  checks: ComparisonCheck[];
  timing: { rent_roll_as_of: string; t12_last_month: string; months_apart: number; status: string } | null;
}

export interface StatedFigure {
  stat: "total_units" | "occupied_units" | "vacant_units" | "occupancy";
  label: string;
  stated: Scalar;
  cell: SourceRef;
}
