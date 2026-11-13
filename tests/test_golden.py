"""Golden files: the full JSON output for each sample, checked in.

Any change to parsing, mapping, validation or metrics shows up as a diff in
tests/golden/*.json that a reviewer can read. To accept an intended change:

    UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from samples import make_charge_lines_xlsx, make_flat_csv_with_problems, make_stacked_header_xlsx
from tieout import clean_file
from tieout.export import to_payload

GOLDEN = Path(__file__).parent / "golden"
SAMPLES = {
    "maple_court": (make_stacked_header_xlsx, "maple_court.xlsx"),
    "flat_export": (make_flat_csv_with_problems, "flat_export.csv"),
    "birch_point": (make_charge_lines_xlsx, "birch_point.xlsx"),
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_output_matches_golden_file(name, tmp_path):
    make, filename = SAMPLES[name]
    payload = to_payload(clean_file(make(tmp_path / filename), as_of=date(2026, 11, 1)))
    payload.pop("tieout_version")
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    golden = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN") or not golden.exists():
        GOLDEN.mkdir(exist_ok=True)
        golden.write_text(text)
    assert text == golden.read_text(), f"{golden.name} changed; rerun with UPDATE_GOLDEN=1 if intended"
