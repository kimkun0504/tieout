from datetime import datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tieout.ingest import UnsupportedFormat, read_grid
from tieout.legacy import LegacyFormatError, read_html_table, sniff
from tieout.pipeline import clean_file

HEADER = ["Unit", "Tenant", "Sq Ft", "Market Rent", "Current Rent", "Lease Start", "Lease End"]
UNITS = [
    ["101", "Smith, Ann", 700, 1500, 1450, datetime(2026, 1, 1), datetime(2026, 12, 31)],
    ["102", "VACANT", 700, 1500, 0, None, None],
    ["103", "Lee, Bo", 900, 1800, 1750.5, datetime(2025, 6, 1), datetime(2027, 5, 31)],
]


def _write_biff(path, title="Oak Court"):
    xlwt = pytest.importorskip("xlwt")
    wb = xlwt.Workbook()
    wb.add_sheet("Notes").write(0, 0, "nothing here")
    ws = wb.add_sheet("Rent Roll")
    datefmt = xlwt.easyxf(num_format_str="mm/dd/yyyy")
    ws.write_merge(0, 0, 0, 3, title)
    ws.write(1, 0, "As of 10/31/2026")
    for c, h in enumerate(HEADER):
        ws.write(3, c, h)
    for r, row in enumerate(UNITS, start=4):
        for c, v in enumerate(row):
            if isinstance(v, datetime):
                ws.write(r, c, v, datefmt)
            elif v is not None:
                ws.write(r, c, v)
    ws.write(7, 0, "Total")
    ws.write(7, 4, 3200.5)
    wb.save(str(path))
    return path


def test_real_xls_workbook_is_read_with_dates_merges_and_fullest_sheet(tmp_path):
    path = _write_biff(tmp_path / "oak.xls")
    assert sniff(path.read_bytes()) == "biff"
    g = read_grid(path)
    assert g.sheet == "Rent Roll" and g.sheets == ["Notes", "Rent Roll"]
    assert (0, 0, 0, 3) in g.merges
    assert g.rows[4][5] == datetime(2026, 1, 1)
    assert g.rows[4][2] == 700 and isinstance(g.rows[4][2], int)

    result = clean_file(path)
    assert [r.get("unit") for r in result.rows] == ["101", "102", "103"]
    assert result.rows[2].get("current_rent") == Decimal("1750.50")
    assert result.ok, [i.message for i in result.open_issues]
    assert str(result.as_of) == "2026-10-31"


def test_named_sheet_in_xls(tmp_path):
    path = _write_biff(tmp_path / "oak.xls")
    assert read_grid(path, "Notes").rows == [["nothing here"]]
    with pytest.raises(ValueError, match="not found"):
        read_grid(path, "Nope")


HTML_EXPORT = """<html><head><meta charset="utf-8"><style>td{x:y}</style></head><body>
<table><tr><td>Report menu</td></tr></table>
<table border=1>
<tr><td colspan=4><b>Oak Court</b></td></tr>
<tr><td>As of 10/31/2026</td></tr>
<tr><th>Unit</th><th>Tenant</th><th>Sq Ft</th><th>Market Rent</th><th>Current Rent</th><th>Lease End</th></tr>
<tr><td>101</td><td>Smith,&nbsp;Ann</td><td>700</td><td>$1,500.00</td><td>$1,450.00</td><td>12/31/2026</td></tr>
<tr><td>102</td><td>VACANT</td><td>700</td><td>$1,500.00</td><td>$0.00</td><td></td></tr>
<tr><td>103</td><td>Lee<br>Bo</td><td>900</td><td>$1,800.00</td><td>$1,750.50</td><td>5/31/2027</td></tr>
<tr><td colspan=4>Total</td><td>$3,200.50</td><td></td></tr>
</table></body></html>"""


def test_html_saved_as_xls_is_read_as_a_table(tmp_path):
    path = tmp_path / "export.xls"
    path.write_text(HTML_EXPORT, encoding="utf-8")
    assert sniff(path.read_bytes()) == "html"
    result = clean_file(path)
    assert [r.get("tenant") for r in result.rows] == ["Smith, Ann", None, "Lee Bo"]  # &nbsp; and <br> are spaces
    assert result.rows[0].get("current_rent") == Decimal("1450.00")
    tie = [i for i in result.issues if i.rule.startswith("total")]
    assert not [i for i in tie if i.severity.value == "error"]
    assert str(result.as_of) == "2026-10-31"


def test_html_rowspan_and_colspan_keep_columns_aligned():
    rows, merges = read_html_table(
        "<table><tr><td rowspan=2>A</td><td colspan=2>B</td><td>C</td></tr>"
        "<tr><td>x</td><td>y</td><td>z</td></tr></table>"
    )
    assert rows == [["A", "B", None, "C"], [None, "x", "y", "z"]]
    assert (0, 0, 1, 0) in merges and (0, 1, 0, 2) in merges


SSML = """<?xml version="1.0"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Rent Roll"><Table>
  <Row><Cell ss:MergeAcross="2"><Data ss:Type="String">Oak Court</Data></Cell></Row>
  <Row ss:Index="3">
   <Cell><Data ss:Type="String">Unit</Data></Cell><Cell><Data ss:Type="String">Tenant</Data></Cell>
   <Cell><Data ss:Type="String">Current Rent</Data></Cell><Cell><Data ss:Type="String">Lease End</Data></Cell>
  </Row>
  <Row><Cell><Data ss:Type="String">101</Data></Cell><Cell><Data ss:Type="String">Smith</Data></Cell>
   <Cell><Data ss:Type="Number">1450</Data></Cell>
   <Cell><Data ss:Type="DateTime">2026-12-31T00:00:00.000</Data></Cell></Row>
  <Row><Cell><Data ss:Type="String">102</Data></Cell>
   <Cell ss:Index="3"><Data ss:Type="Number">1500.25</Data></Cell></Row>
 </Table></Worksheet>
</Workbook>"""


def test_excel_2003_xml_spreadsheet(tmp_path):
    path = tmp_path / "x.xls"
    path.write_text(SSML, encoding="utf-8")
    g = read_grid(path)
    assert g.sheet == "Rent Roll"
    assert g.rows[0] == ["Oak Court"] and (0, 0, 0, 2) in g.merges
    assert g.rows[1] == []
    assert g.rows[3] == ["101", "Smith", 1450, datetime(2026, 12, 31)]
    assert g.rows[4] == ["102", None, 1500.25]


def test_xml_with_entities_is_refused(tmp_path):
    path = tmp_path / "bomb.xls"
    path.write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">&a;</Workbook>'
    )
    with pytest.raises(UnsupportedFormat, match="DOCTYPE"):
        read_grid(path)


def test_xlsx_saved_with_an_xls_name_is_read_as_xlsx(tmp_path):
    from samples import make_stacked_header_xlsx

    src = make_stacked_header_xlsx(tmp_path / "m.xlsx")
    path = tmp_path / "m.xls"
    path.write_bytes(src.read_bytes())
    assert len(clean_file(path).rows) == len(clean_file(src).rows) > 0


@pytest.mark.parametrize(
    "content, match",
    [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "Could not read"),
        (b"PK\x03\x04 just some zip", "not a valid .xlsx"),
        (b"%PDF-1.4 nope", "not an Excel workbook"),
    ],
)
def test_damaged_or_mislabelled_xls_gives_a_clear_error(tmp_path, content, match):
    path = tmp_path / "bad.xls"
    path.write_bytes(content)
    with pytest.raises(UnsupportedFormat, match=match):
        read_grid(path)


_TAGS = st.sampled_from(
    [
        "<table>",
        "</table>",
        "<tr>",
        "</tr>",
        "<td>",
        "</td>",
        "<th>",
        "<td colspan=3>",
        "<td rowspan=4>",
        "<td rowspan=x>",
        "<br>",
        "<script>",
        "</script>",
        "&nbsp;",
        "1,200",
        "Unit",
        " ",
    ]
)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.one_of(_TAGS, st.text(max_size=5)), max_size=60))
def test_html_reader_never_crashes_and_merge_anchors_exist(parts):
    try:
        rows, merges = read_html_table("".join(parts))
    except LegacyFormatError:
        return
    for r0, c0, r1, c1 in merges:
        assert 0 <= r0 <= r1 and 0 <= c0 <= c1
        assert len(rows) > r0 and len(rows[r0]) > c0
