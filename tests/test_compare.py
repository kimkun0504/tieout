from datetime import date

from tieout import clean_file
from tieout.compare import compare
from tieout.ingest import read_grid
from tieout.t12 import read_t12


def _t12(tmp_path, gpr_last="10000", vacancy_last="-1000"):
    months = ["Jan-26", "Feb-26", "Mar-26"]
    rows = [
        ",".join(["Description", *months, "Total"]),
        "Income",
        ",".join(["Gross Potential Rent", "10000", "10000", gpr_last, str(20000 + int(gpr_last))]),
        ",".join(["Vacancy Loss", "-1000", "-1000", vacancy_last, str(-2000 + int(vacancy_last))]),
        ",".join(
            [
                "Total Income",
                "9000",
                "9000",
                str(int(gpr_last) + int(vacancy_last)),
                str(18000 + int(gpr_last) + int(vacancy_last)),
            ]
        ),
    ]
    path = tmp_path / "t12.csv"
    path.write_text("\n".join(rows) + "\n")
    return read_t12(read_grid(path))


def _rent_roll(tmp_path, units=10, vacant=1, rent=1000, market=1000):
    rows = ["Unit,Tenant,Market Rent,Rent"]
    for i in range(units):
        occupied = i >= vacant
        rows.append(f"{100 + i},{'T' + str(i) if occupied else 'VACANT'},{market},{rent if occupied else 0}")
    path = tmp_path / "rr.csv"
    path.write_text("\n".join(rows) + "\n")
    return clean_file(path, as_of=date(2026, 4, 1))


def by_metric(result):
    return {c["metric"]: c for c in result["checks"]}


def test_consistent_documents(tmp_path):
    out = compare(_rent_roll(tmp_path), _t12(tmp_path))
    checks = by_metric(out)
    assert checks["gross_potential_rent"]["status"] == "consistent"  # 10,000 vs 10,000
    assert checks["rent_in_place"]["status"] == "consistent"  # 9,000 vs 9,000
    assert checks["economic_occupancy"]["status"] == "consistent"
    assert out["timing"] == {
        "rent_roll_as_of": "2026-04-01",
        "t12_last_month": "2026-03",
        "months_apart": 1,
        "status": "consistent",
    }


def test_missing_units_show_up_as_a_gpr_gap(tmp_path):
    out = compare(_rent_roll(tmp_path, units=9, vacant=0), _t12(tmp_path, vacancy_last="-1000"))
    gpr = by_metric(out)["gross_potential_rent"]
    assert gpr["rent_roll"] == "9000.00" and gpr["t12"] == "10000.00"
    assert gpr["difference"] == "-1000.00" and gpr["pct"] == -0.1 and gpr["status"] == "investigate"


def test_small_gap_is_a_check(tmp_path):
    out = compare(_rent_roll(tmp_path), _t12(tmp_path, gpr_last="10400", vacancy_last="-1400"))
    assert by_metric(out)["gross_potential_rent"]["status"] == "check"  # 3.8% apart


def test_missing_figures_are_unavailable_not_zero(tmp_path):
    rows = ["Unit,Tenant,Rent", "101,A,1000"]
    path = tmp_path / "rr.csv"
    path.write_text("\n".join(rows) + "\n")
    out = compare(clean_file(path), _t12(tmp_path))
    checks = by_metric(out)
    assert checks["gross_potential_rent"]["status"] == "unavailable"  # no market rent column
    assert checks["economic_occupancy"]["status"] == "unavailable"
    assert out["timing"] is None  # no report date
