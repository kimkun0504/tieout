import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from samples import make_flat_csv_with_problems, make_stacked_header_xlsx  # noqa: E402


@pytest.fixture
def stacked_xlsx(tmp_path: Path) -> Path:
    return make_stacked_header_xlsx(tmp_path / "maple_court.xlsx")


@pytest.fixture
def flat_csv(tmp_path: Path) -> Path:
    return make_flat_csv_with_problems(tmp_path / "flat_export.csv")
