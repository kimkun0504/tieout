import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { issue, result } from "../test/fixtures";
import { IssueQueue } from "./IssueQueue";
import { TieOutStrip } from "./TieOutStrip";

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("TieOutStrip", () => {
  it("shows the gap when a total doesn't tie out, and selects the total row", async () => {
    const onSelect = vi.fn();
    wrap(<TieOutStrip result={result()} onSelect={onSelect} />);
    expect(screen.getByText("7,025.00")).toBeInTheDocument();
    expect(screen.getByText("Units add to 6,975.00, off by 50.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Total, rent/ }));
    expect(onSelect).toHaveBeenCalledWith(7, "current_rent");
  });

  it("marks a total as tying out", () => {
    const r = result({ issues: [issue({ rule: "total_ties_out", severity: "info" })] });
    wrap(<TieOutStrip result={r} onSelect={() => {}} />);
    expect(screen.getByText("ties")).toBeInTheDocument();
  });

  it("shows footer figures and flags one that disagrees", () => {
    const cell = (c: string) => ({ file: "x", sheet: "s", cell: c, row: 20, col: 2 });
    const r = result({
      stated_figures: [
        { stat: "total_units", label: "Total Units", stated: 5, cell: cell("B19") },
        { stat: "occupancy", label: "Occupancy %", stated: 0.9, cell: cell("B20") },
      ],
      issues: [
        issue({ rule: "stated_figure_ties", severity: "info", row: null, field: null, cells: ["B19"], message: "ok" }),
        issue({
          rule: "stated_figure_differs",
          severity: "warning",
          row: null,
          field: null,
          cells: ["B20"],
          message: "The report states occupancy of 90.0% (B20), but 4 of 5 units read as occupied (80.0%). Check.",
        }),
      ],
    });
    wrap(<TieOutStrip result={r} onSelect={() => {}} />);
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText("But 4 of 5 units read as occupied (80.0%)")).toBeInTheDocument();
    expect(screen.getByText(/1 doesn't agree/)).toBeInTheDocument();
  });

  it("explains when there are no totals", () => {
    wrap(<TieOutStrip result={result({ totals: [] })} onSelect={() => {}} />);
    expect(screen.getByText(/no total rows/)).toBeInTheDocument();
  });
});

describe("IssueQueue", () => {
  afterEach(() => vi.restoreAllMocks());

  it("requires a note to accept an issue and sends it to the API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job: {}, result: result() }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    wrap(<IssueQueue jobId="j1" result={result()} onSelect={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept as is" }));
    const accept = screen.getByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason for accepting"), "Source system total is stale");
    await userEvent.click(accept);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/jobs/j1/acknowledgments");
    expect(JSON.parse(String(init!.body))).toEqual({ issue_id: "a1b2c3d4e5f6", note: "Source system total is stale" });
  });

  it("shows an empty state when nothing is open", () => {
    wrap(<IssueQueue jobId="j1" result={result({ issues: [] })} onSelect={() => {}} />);
    expect(screen.getByText(/Nothing left to review/)).toBeInTheDocument();
  });

  it("surfaces API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "A note is required to accept an issue" }), { status: 422 }),
    );
    wrap(<IssueQueue jobId="j1" result={result()} onSelect={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept as is" }));
    await userEvent.type(screen.getByLabelText("Reason for accepting"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A note is required");
  });
});

describe("UnitsTable keyboard navigation", () => {
  it("moves between cells with the arrow keys like a spreadsheet", async () => {
    const { UnitsTable } = await import("./UnitsTable");
    const r = result();
    r.rows.push({
      source_row: 3,
      section: null,
      fields: {
        unit: { value: "1B", raw: "1B", source: null, derived: false },
        current_rent: { value: "100.00", raw: "100", source: null, derived: false },
      },
      charges: [],
    });
    const onSelect = vi.fn();
    wrap(<UnitsTable result={r} selection={{ row: 2, field: "unit" }} onSelect={onSelect} />);
    const start = screen.getByRole("button", { name: "Unit for row 2" });
    expect(start).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("button", { name: "Unit for row 3" })).toHaveAttribute("tabindex", "-1");
    start.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onSelect).toHaveBeenLastCalledWith({ row: 3, field: "unit" });
    await userEvent.keyboard("{ArrowRight}");
    expect(onSelect).toHaveBeenLastCalledWith({ row: 2, field: "current_rent" });
  });
});

describe("T12View", () => {
  it("shows which tie-out direction fails and lists the issue", async () => {
    const { T12View } = await import("./T12View");
    const months = ["2026-01", "2026-02"];
    const line = (row: number, name: string, kind: "line" | "subtotal" | "noi", section: string, a: string[]) => ({
      source_row: row, code: null, name, section, kind, category: kind === "line" ? "gross_potential_rent" : null,
      amounts: a, cells: a.map((_, i) => `${"CD"[i]}${row}`), total: null, total_cell: null, month_sum: "0",
    });
    const data = {
      job: { id: "j", filename: "t12.xlsx", suffix: ".xlsx", size: 1, sha256: "", uploaded_at: "", updated_at: "", sheet: null, as_of: null, last_summary: {}, last_ok: false },
      result: {
        document_type: "t12" as const, tieout_version: "0.1.0", source: { file: "t12.xlsx", sheet: "T12", header_row: 1 },
        ok: false, months,
        summary: { period: "Jan 2026 to Feb 2026", months: 2, line_items: 1, total_income: "200.00", total_expenses: "0.00",
          noi: "200.00", expense_ratio: 0, by_category: { gross_potential_rent: "200.00" }, uncategorized: 0, errors: 1, warnings: 0 },
        lines: [line(3, "Rent", "line", "income", ["100.00", "100.00"]), line(5, "Net Operating Income", "noi", "noi", ["100.00", "150.00"])],
        issues: [issue({ rule: "t12_noi_mismatch", row: 5, field: null, cells: ["D5"], message: "NOI for Feb 2026 is 150.00, but income 100.00 minus expenses 0.00 is 100.00 (difference 50.00)." })],
      },
    };
    wrap(<T12View data={data as never} />);
    expect(screen.getByText("1 error to resolve")).toBeInTheDocument();
    expect(screen.getAllByText("ties")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "1 place doesn't tie out" })).toBeInTheDocument();
    expect(screen.getByText("NOI isn't income minus expenses")).toBeInTheDocument();
    expect(screen.getByTitle(/^D5: NOI for Feb 2026/)).toHaveTextContent("150.00");
  });
});

describe("Upload", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads several files one after another and lists each result", async () => {
    const { api } = await import("../lib/api");
    const { JobsPage } = await import("./JobsPage");
    vi.spyOn(api, "jobs").mockResolvedValue([]);
    const upload = vi
      .spyOn(api, "upload")
      .mockResolvedValueOnce({ job: { id: "a", last_ok: true, last_summary: { warnings: 0 } } } as never)
      .mockRejectedValueOnce(new Error("Unsupported file type .docx"));
    wrap(<JobsPage />);
    const files = [new File(["x"], "oak.xlsx"), new File(["y"], "notes.docx")];
    await userEvent.upload(screen.getByLabelText("Rent roll or T-12 files"), files, { applyAccept: false });
    expect(await screen.findByText("Unsupported file type .docx")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "oak.xlsx" })).toHaveAttribute("href", "#/jobs/a");
    expect(screen.getByText("Ties out")).toBeInTheDocument();
    expect(upload).toHaveBeenCalledTimes(2);
  });
});
