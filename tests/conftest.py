import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from samples import make_flat_csv_with_problems, make_stacked_header_xlsx


@pytest.fixture
def stacked_xlsx(tmp_path: Path) -> Path:
    return make_stacked_header_xlsx(tmp_path / "maple_court.xlsx")


@pytest.fixture
def flat_csv(tmp_path: Path) -> Path:
    return make_flat_csv_with_problems(tmp_path / "flat_export.csv")


@pytest.fixture
def charges_xlsx(tmp_path: Path) -> Path:
    from samples import make_charge_lines_xlsx

    return make_charge_lines_xlsx(tmp_path / "birch_point.xlsx")
