import csv
import json

from tieout import clean_file
from tieout.export import write_all


def test_csv_neutralises_formula_text(tmp_path):
    """Finding 14: '=HYPERLINK(...)' in a tenant cell would run when the CSV is opened in Excel."""
    src = tmp_path / "inj.csv"
    src.write_text('Unit,Tenant,Rent\n101,"=HYPERLINK(""http://x"",""a"")",1000\n102,@SUM(A1),-50\n', newline="")
    paths = write_all(clean_file(src), tmp_path / "out")
    rows = list(csv.DictReader(paths["csv"].open()))
    assert rows[0]["tenant"].startswith("'=")
    assert rows[1]["tenant"].startswith("'@")
    assert rows[1]["current_rent"] == "-50.00"  # real negative numbers are not prefixed


def test_json_money_is_exact_decimal_string(tmp_path):
    src = tmp_path / "m.csv"
    src.write_text("Unit,Tenant,Rent\n101,A,1425.10\n102,B,0.1\n102b,C,0.2\n", newline="")
    paths = write_all(clean_file(src), tmp_path / "out")
    data = json.loads(paths["json"].read_text())
    assert data["rows"][0]["fields"]["current_rent"]["value"] == "1425.10"
    assert data["summary"]["total_current_rent"] == "1425.40"  # no 0.30000000000000004


def test_report_escapes_pipes(tmp_path):
    src = tmp_path / "p.csv"
    src.write_text("Unit,Tenant,Rent,Notes | Misc\n101,A,1000,x\n", newline="")
    paths = write_all(clean_file(src), tmp_path / "out")
    assert "Notes \\| Misc" in paths["report"].read_text()


def test_jsonl_records_are_retrieval_ready(stacked_xlsx, tmp_path):
    from tieout.export import to_jsonl_records

    records = to_jsonl_records(clean_file(stacked_xlsx))
    units = [r for r in records if r["type"] == "unit"]
    assert len(units) == 5 and records[-1]["type"] == "property_summary"
    first = units[0]
    assert first["text"] == (
        "Unit 101 (1x1, 650 sq ft) in Building A is occupied, leased to Garcia, Maria. "
        "Rent is $1,425.00 per month against market rent of $1,450.00. Also: deposit $500.00. "
        "Lease runs Feb 1, 2026 to Jan 31, 2027. Moved in Feb 1, 2024."
    )
    assert first["fields"]["current_rent"] == "1425.00"
    assert first["metadata"]["cells"]["current_rent"] == "F8"
    assert first["metadata"]["source_row"] == 8
    assert "status" in units[1]["metadata"]["derived_fields"]  # VACANT marker -> status
    assert "5 units, 4 occupied (80.0% physical occupancy)" in records[-1]["text"]


def test_jsonl_can_remove_tenant_names(stacked_xlsx):
    from tieout.export import to_jsonl_records

    for rec in to_jsonl_records(clean_file(stacked_xlsx), redact_tenants=True):
        assert "Garcia" not in rec["text"] and "tenant" not in rec["fields"]


def test_xlsx_keeps_formula_like_text_as_exact_text(tmp_path):
    from openpyxl import load_workbook

    src = tmp_path / "inj.csv"
    src.write_text('Unit,Tenant,Rent\n101,"=HYPERLINK(""http://x"",""a"")",1000\n', newline="")
    paths = write_all(clean_file(src), tmp_path / "out")
    cell = load_workbook(paths["xlsx"])["Rent Roll"]["D2"]
    assert cell.data_type == "s"
    assert cell.value == '=HYPERLINK("http://x","a")'  # exactly as in the source, but text


def test_duplicate_headers_can_be_overridden_separately(tmp_path):
    from tieout.review import Review

    src = tmp_path / "dup.csv"
    src.write_text("Unit,Tenant,Rent,Rent\n101,A,1000,1100\n", newline="")
    first = clean_file(src)
    assert [m.field for m in first.mappings] == ["unit", "tenant", "current_rent", None]
    review = Review()
    review.override_mapping("Rent", None)
    review.override_mapping("Rent #2", "current_rent")
    r = clean_file(src, review=review)
    assert [m.field for m in r.mappings] == ["unit", "tenant", None, "current_rent"]
    assert str(r.rows[0].get("current_rent")) == "1100.00"
    from tieout.export import to_payload

    assert [m["key"] for m in to_payload(r)["mappings"]] == ["Unit", "Tenant", "Rent", "Rent #2"]


def test_two_overrides_for_one_field_keep_the_leftmost(tmp_path):
    from tieout.review import Review

    src = tmp_path / "two.csv"
    src.write_text("Unit,Tenant,A,B\n101,Lee,1000,1100\n", newline="")
    review = Review()
    review.override_mapping("B", "current_rent")
    review.override_mapping("A", "current_rent")
    r = clean_file(src, review=review)
    assert {m.header: m.field for m in r.mappings} == {
        "Unit": "unit",
        "Tenant": "tenant",
        "A": "current_rent",
        "B": None,
    }


def test_outputs_are_utf8_whatever_the_platform_default(tmp_path):
    from tieout.export import write_all
    from tieout.ingest import Grid
    from tieout.pipeline import clean_file

    rows = [["Unit", "Tenant", "Rent"], ["101", "Zoë Ångström", 1200], ["102", "李小龍", 1300]]
    result = clean_file("x.csv", grid=Grid("x.csv", "x", rows))
    paths = write_all(result, tmp_path)
    for key in ("csv", "report", "jsonl", "json"):
        paths[key].read_bytes().decode("utf-8")  # raises if written in a legacy code page
    assert "李小龍" in paths["csv"].read_text(encoding="utf-8")
    assert "Zoë Ångström" in paths["jsonl"].read_text(encoding="utf-8")
