import { fieldLabel, fmtDate, fmtMoney, fmtNumber, fmtPct, ruleLabel } from "./format";
import { colLetter, issuesByRow, worstSeverity } from "./selection";
import { parseHash } from "./route";
import { issue, result } from "../test/fixtures";

describe("format", () => {
  it("formats exact decimal strings as money with accounting negatives", () => {
    expect(fmtMoney("1425.10")).toBe("1,425.10");
    expect(fmtMoney("-100.00")).toBe("(100.00)");
    expect(fmtMoney(null)).toBe("");
    expect(fmtMoney("not money")).toBe("not money");
  });

  it("formats dates without time-zone drift", () => {
    // new Date("2026-03-01") would print Feb 28 in US time zones; we parse by hand.
    expect(fmtDate("2026-03-01")).toBe("Mar 1, 2026");
    expect(fmtDate(null)).toBe("");
  });

  it("formats numbers and percentages", () => {
    expect(fmtNumber(3965)).toBe("3,965");
    expect(fmtNumber("812.5")).toBe("812.5");
    expect(fmtPct(0.8)).toBe("80.0%");
    expect(fmtPct(null)).toBe("–");
  });

  it("names fields and rules in plain language", () => {
    expect(fieldLabel("current_rent")).toBe("Rent");
    expect(fieldLabel(null)).toBe("Not used");
    expect(fieldLabel("some_new_field")).toBe("Some new field");
    expect(ruleLabel("total_does_not_tie_out")).toBe("Total doesn't tie out");
    expect(ruleLabel("brand_new_rule")).toBe("brand new rule");
  });
});

describe("selection helpers", () => {
  it("converts column indexes to spreadsheet letters", () => {
    expect([0, 25, 26, 27, 701, 702].map(colLetter)).toEqual(["A", "Z", "AA", "AB", "ZZ", "AAA"]);
  });

  it("groups open, non-info issues by row", () => {
    const r = result({
      issues: [
        issue({ id: "1", row: 2, severity: "warning" }),
        issue({ id: "2", row: 2, severity: "error" }),
        issue({ id: "3", row: 3, severity: "info" }),
        issue({ id: "4", row: 4, acknowledgment: { issue_id: "4", note: "ok", author: "", at: "" } }),
      ],
    });
    const map = issuesByRow(r);
    expect([...map.keys()]).toEqual([2]);
    expect(worstSeverity(map.get(2))).toBe("error");
    expect(worstSeverity(undefined)).toBeNull();
  });
});

describe("routing", () => {
  it("only accepts real job ids", () => {
    expect(parseHash("#/jobs/0123456789abcdef0123456789abcdef")).toEqual({ page: "job", id: "0123456789abcdef0123456789abcdef" });
    expect(parseHash("#/jobs/../../etc")).toEqual({ page: "jobs" });
    expect(parseHash("")).toEqual({ page: "jobs" });
  });
});
