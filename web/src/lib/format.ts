import type { FieldType, Scalar } from "./types";

const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const oneDp = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

/** Money arrives as an exact decimal string. Negative amounts use accounting parentheses. */
export function fmtMoney(v: Scalar | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n < 0 ? `(${money.format(-n)})` : money.format(n);
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtNumber(v: Scalar | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? (Number.isInteger(n) ? whole.format(n) : oneDp.format(n)) : String(v);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-01" -> "Mar 1, 2026". Parsed by hand so the date never shifts by time zone. */
export function fmtDate(v: Scalar | undefined): string {
  if (typeof v !== "string") return v === null || v === undefined ? "" : String(v);
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  if (!m) return v;
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

export function fmtMonth(v: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(v);
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]!.slice(2)}` : v;
}

export function fmtValue(v: Scalar | undefined, type: FieldType | undefined): string {
  switch (type) {
    case "money":
      return fmtMoney(v);
    case "number":
      return fmtNumber(v);
    case "date":
      return fmtDate(v);
    default:
      return v === null || v === undefined ? "" : String(v);
  }
}

export function fmtTimestamp(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const LABELS: Record<string, string> = {
  unit: "Unit",
  unit_type: "Type",
  sqft: "Sq ft",
  tenant: "Tenant",
  status: "Status",
  market_rent: "Market rent",
  current_rent: "Rent",
  concessions: "Concessions",
  other_charges: "Other charges",
  total_charges: "Total charges",
  deposit: "Deposit",
  move_in: "Move-in",
  lease_start: "Lease start",
  lease_end: "Lease end",
  charge_code: "Charge code",
  charge_amount: "Charge amount",
};

export function fieldLabel(name: string | null | undefined): string {
  if (!name) return "Not used";
  return LABELS[name] ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Plain-language names for validation rules. */
const RULES: Record<string, string> = {
  total_does_not_tie_out: "Total doesn't tie out",
  total_ties_out: "Total ties out",
  total_not_checkable: "Total can't be checked",
  duplicate_unit: "Duplicate unit",
  lease_dates_reversed: "Lease ends before it starts",
  vacant_with_rent: "Vacant unit with rent",
  occupied_without_tenant: "Occupied, no tenant",
  occupied_without_rent: "Occupied, no rent",
  negative_rent: "Negative rent",
  rent_far_from_market: "Rent far from market",
  lease_expired: "Lease expired",
  unparsed_value: "Value couldn't be read",
  missing_unit: "Missing unit",
  required_column_missing: "Required column missing",
  low_confidence_mapping: "Mapping needs a check",
  unmapped_column: "Column not used",
  status_inferred: "Status inferred",
  correction_orphaned: "Correction has no row",
  rent_per_sqft_outlier: "Rent per sq ft out of line",
  move_in_after_report_date: "Move-in after report date",
};

export function ruleLabel(rule: string): string {
  return RULES[rule] ?? rule.replace(/_/g, " ");
}
