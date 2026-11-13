import pytest

from tieout import clean_file
from tieout.mapping import TemplateStore, map_columns


def fields(headers):
    return {m.header: m.field for m in map_columns(dict(enumerate(headers)))}


@pytest.mark.parametrize(
    "header, field",
    [
        ("Unit", "unit"),
        ("Unit #", "unit"),
        ("Apt", "unit"),
        ("Resident Name", "tenant"),
        ("Lessee", "tenant"),
        ("Sq. Ft.", "sqft"),
        ("Unit Sq Ft", "sqft"),
        ("RSF", "sqft"),
        ("Mkt. Rent", "market_rent"),
        ("Actual Rent", "current_rent"),
        ("Rent", "current_rent"),
        ("Lease Expiration Date", "lease_end"),
        ("Lease From", "lease_start"),
        ("Move-In", "move_in"),
        ("Unit Status", "status"),
        ("Security Deposit", "deposit"),
    ],
)
def test_common_headers_map(header, field):
    assert fields([header])[header] == field


@pytest.mark.parametrize(
    "header",
    [
        "Monthly Rent/SF",
        "Market Rent PSF",
        "Annual Rent",
        "Prior Rent",
        "Budget Rent",
        "Rent Variance",
        "Balance Due",
        "YTD Rent",
    ],
)
def test_qualified_headers_do_not_map_to_monthly_rent(header):
    """Finding 10: 'Monthly Rent/SF' used to map to current_rent and get summed as monthly rent."""
    assert fields([header])[header] not in ("current_rent", "market_rent")


def test_each_field_used_once_best_score_wins():
    f = fields(["Rent", "Actual Rent", "Market Rent"])
    assert list(f.values()).count("current_rent") == 1


def test_template_maps_by_header_name_not_position(tmp_path):
    """Finding 5: an extra blank column shifted positions and the template mapped Tenant as rent."""
    from openpyxl import Workbook

    def save(rows, name):
        wb = Workbook()
        for r in rows:
            wb.active.append(r)
        wb.save(tmp_path / name)
        return tmp_path / name

    store = TemplateStore(tmp_path / "tpl")
    first = clean_file(save([["Unit", "Tenant", "Rent"], ["101", "A", 1000]], "a.xlsx"))
    store.save(first.header.headers, first.mappings, "test")

    shifted = clean_file(save([["Unit", None, "Tenant", "Rent"], ["101", None, "A", 1000]], "b.xlsx"), templates=store)
    assert {m.header: (m.field, m.method) for m in shifted.mappings} == {
        "Unit": ("unit", "template"),
        "Tenant": ("tenant", "template"),
        "Rent": ("current_rent", "template"),
    }
    assert shifted.rows[0].get("current_rent") == 1000


def test_old_position_based_templates_are_ignored(tmp_path):
    import json

    from tieout.mapping import header_fingerprint

    store = TemplateStore(tmp_path)
    fp = header_fingerprint(["Unit", "Rent"])
    (tmp_path / f"{fp}.json").write_text(json.dumps({"mappings": [{"column": 0, "field": "rent"}]}))
    assert store.load({0: "Unit", 1: "Rent"}) is None


class FakeMapper:
    """Stands in for an LLM: places one header and tries to grab an already-taken field."""

    def __init__(self):
        self.seen = None

    def suggest(self, headers, free_fields):
        self.seen = (headers, free_fields)
        return {"Lease Signed Rate": ("current_rent", 0.99), "Tenant ID Code": ("unit", 0.9)}


def test_pluggable_mapper_fills_gaps_but_never_overrides_rules():
    mapper = FakeMapper()
    ms = map_columns({0: "Unit", 1: "Tenant", 2: "Lease Signed Rate", 3: "Tenant ID Code"}, {2: ["1,200.00"]}, mapper)
    by_header = {m.header: m for m in ms}
    assert by_header["Lease Signed Rate"].field == "current_rent"
    assert by_header["Lease Signed Rate"].method == "mapper"
    assert by_header["Lease Signed Rate"].confidence == 0.8  # capped below rule matches
    assert by_header["Tenant ID Code"].field is None  # 'unit' was already taken by the rules
    assert "unit" not in mapper.seen[1]
    assert mapper.seen[0]["Lease Signed Rate"] == ["1,200.00"]
