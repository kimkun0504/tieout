import type { Issue, Result } from "../lib/types";

export function issue(over: Partial<Issue> = {}): Issue {
  return {
    id: "a1b2c3d4e5f6",
    severity: "error",
    rule: "total_does_not_tie_out",
    message: "'Total' reports rent of 7,025.00, but the 5 units it covers add up to 6,975.00 (difference 50.00).",
    row: 7,
    field: "current_rent",
    cells: ["F7"],
    acknowledgment: null,
    ...over,
  };
}

export function result(over: Partial<Result> = {}): Result {
  return {
    tieout_version: "0.1.0",
    source: { file: "flat.csv", sheet: "flat", header_rows: [1] },
    ok: false,
    summary: {
      units: 1, status_counts: { occupied: 1 }, physical_occupancy: 1, total_current_rent: "6975.00",
      total_market_rent: null, total_sqft: null, errors: 1, warnings: 0, acknowledged: 0, corrections: 0,
    },
    metrics: {
      units: 1, occupied_units: 1, vacant_units: 0, physical_occupancy: 1, economic_occupancy: null,
      gross_potential_rent: null, in_place_rent: "6975.00", loss_to_lease: null, loss_to_lease_pct: null,
      vacancy_loss: null, concessions: null, avg_in_place_rent: "6975.00", avg_market_rent: null,
      avg_rent_per_sqft: null, unit_mix: [],
    },
    fields: [{ name: "unit", type: "text", description: "" }, { name: "current_rent", type: "money", description: "" }],
    mappings: [],
    rows: [
      {
        source_row: 2,
        section: null,
        fields: {
          unit: { value: "1A", raw: "1A", source: { file: "flat.csv", sheet: "flat", cell: "A2", row: 2, col: 1 }, derived: false },
          current_rent: { value: "6975.00", raw: "6,975.00", source: { file: "flat.csv", sheet: "flat", cell: "B2", row: 2, col: 2 }, derived: false },
        },
        charges: [],
      },
    ],
    totals: [
      {
        row: 7,
        label: "Total",
        section: null,
        covers_rows: [2],
        amounts: { current_rent: { value: "7025.00", raw: "7,025.00", source: null, derived: false } },
        computed: { current_rent: "6975.00" },
      },
    ],
    issues: [issue()],
    skipped: {},
    review: { mapping_overrides: {}, corrections: [], acknowledgments: [], audit: [] },
    ...over,
  };
}
