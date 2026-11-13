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
