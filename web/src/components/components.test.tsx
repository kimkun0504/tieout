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
