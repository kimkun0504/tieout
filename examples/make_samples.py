"""Write the two synthetic sample rent rolls to examples/data/ so you can try the CLI.

python examples/make_samples.py
tieout clean examples/data/maple_court.xlsx
tieout clean examples/data/flat_export.csv --as-of 2026-11-01
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from samples import make_flat_csv_with_problems, make_stacked_header_xlsx  # noqa: E402

out = ROOT / "examples" / "data"
out.mkdir(parents=True, exist_ok=True)
print(make_stacked_header_xlsx(out / "maple_court.xlsx"))
print(make_flat_csv_with_problems(out / "flat_export.csv"))
