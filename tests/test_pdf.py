import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

from samples import make_pdf_rent_roll
from tieout import clean_file
from tieout.ingest import UnsupportedFormat, read_grid


@pytest.mark.parametrize("ruled", [True, False], ids=["ruled", "no grid lines"])
def test_pdf_rent_roll_reads_and_ties_out(tmp_path, ruled):
    r = clean_file(make_pdf_rent_roll(tmp_path / "cedar.pdf", ruled))
    assert [x.get("unit") for x in r.rows] == ["C101", "C102", "C103", "C104", "C105", "C106"]
    assert r.ok
    assert {i.field for i in r.issues if i.rule == "total_ties_out"} == {"sqft", "market_rent", "current_rent"}
    assert r.skipped.get("repeated_header") == 1  # the header repeated on page 2


def test_pdf_values_and_provenance(tmp_path):
    r = clean_file(make_pdf_rent_roll(tmp_path / "cedar.pdf"))
    c101, c102, c104 = r.rows[0], r.rows[1], r.rows[3]
    assert c101.get("tenant") == "Novak, Petra"
    assert str(c101.get("current_rent")) == "1500.00"
    assert c102.get("status") == "vacant" and c102.get("tenant") is None
    assert c104.get("status") == "notice"
    assert c101.values["current_rent"].source.sheet == "page 1"
    assert c104.values["current_rent"].source.sheet == "page 2"


def test_pdf_without_text_is_refused_with_advice(tmp_path):
    from reportlab.pdfgen import canvas

    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path))
    c.rect(50, 50, 200, 200, fill=1)  # an image-like page with no text
    c.save()
    with pytest.raises(UnsupportedFormat, match="no text layer"):
        read_grid(path)
