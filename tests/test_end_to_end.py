"""One realistic export exercising many features at once.

tests/data/yardi_style_export.xls is synthetic: an HTML table saved with an .xls
name (as "Export to Excel" buttons do), a Yardi-style "As Of =" line above a
printed date, "Apt" unit codes, an NTV status, an accounting dash for zero rent,
a future-residents section that repeats a unit, and footer statistics.
"""

from datetime import date
from pathlib import Path

from tieout.cli import main
from tieout.pipeline import clean_file

SAMPLE = Path(__file__).parent / "data" / "yardi_style_export.xls"


def test_yardi_style_export_reads_correctly():
    r = clean_file(SAMPLE)
    s = r.summary()
    assert r.as_of == date(2026, 10, 31)  # not the printed date
    assert s["units"] == 3 and s["future_leases"] == 1
    assert s["status_counts"] == {"occupied": 1, "notice": 1, "vacant": 1}
    assert s["total_current_rent"] == "2850.00"
    assert r.ok and s["warnings"] == 0
    rules = {i.rule for i in r.issues}
    assert {"total_ties_out", "stated_figure_ties", "future_leases"} <= rules


def test_batch_on_the_sample_ties_out(tmp_path):
    assert main(["batch", str(SAMPLE.parent), "-o", str(tmp_path), "--strict"]) == 0
