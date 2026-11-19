import csv
from pathlib import Path

from samples import make_flat_csv_with_problems, make_stacked_header_xlsx, make_t12_xlsx
from tieout.batch import find_files, run_batch
from tieout.cli import main


def _portfolio(root: Path) -> Path:
    root.mkdir()
    make_stacked_header_xlsx(root / "Oak Court.xlsx")
    make_flat_csv_with_problems(root / "maple.csv")
    make_t12_xlsx(root / "oak t12.xlsx")
    (root / "notes.docx").write_bytes(b"not a rent roll")  # unsupported: ignored
    (root / "~$Oak Court.xlsx").write_bytes(b"lock")  # Excel lock file: ignored
    (root / "broken.xlsx").write_bytes(b"this is not a zip")  # supported suffix, unreadable
    sub = root / "2025"
    sub.mkdir()
    make_t12_xlsx(sub / "oak t12.xlsx", noi_off_by=250)
    return root


def _summary(out: Path) -> dict[str, dict[str, str]]:
    with (out / "summary.csv").open(newline="", encoding="utf-8") as fh:
        return {r["file"]: r for r in csv.DictReader(fh)}


def test_find_files_skips_lock_and_unsupported_files(tmp_path):
    root = _portfolio(tmp_path / "in")
    assert [p.name for p in find_files(root)] == ["broken.xlsx", "maple.csv", "Oak Court.xlsx", "oak t12.xlsx"]
    assert len(find_files(root, recursive=True)) == 5


def test_batch_cleans_each_file_and_records_failures(tmp_path):
    root = _portfolio(tmp_path / "in")
    out = tmp_path / "out"
    result = run_batch(root, out, recursive=True)
    rows = _summary(out)

    assert set(rows) == {"broken.xlsx", "maple.csv", "Oak Court.xlsx", "oak t12.xlsx", "2025/oak t12.xlsx"}
    assert rows["broken.xlsx"]["status"] == "failed" and rows["broken.xlsx"]["message"]
    assert rows["oak t12.xlsx"]["document_type"] == "t12"
    assert rows["oak t12.xlsx"]["status"] == "ties out"
    assert rows["2025/oak t12.xlsx"]["status"] == "needs review"
    assert int(rows["2025/oak t12.xlsx"]["errors"]) >= 1
    assert rows["Oak Court.xlsx"]["document_type"] == "rent_roll"
    assert int(rows["Oak Court.xlsx"]["units_or_lines"]) > 0
    assert rows["Oak Court.xlsx"]["as_of"] == "2026-10-31"  # read from the title rows
    assert rows["maple.csv"]["status"] == "needs review"

    # same stem in two folders must not overwrite each other's outputs
    outputs = {r["output"] for r in rows.values() if r["output"]}
    assert len(outputs) == 4
    for o in outputs:
        assert any(Path(o).iterdir())
    assert not result.ok and len(result.failed) == 1


def test_batch_cli_strict_exit_codes(tmp_path, capsys):
    root = _portfolio(tmp_path / "in")
    assert main(["batch", str(root), "-o", str(tmp_path / "a")]) == 0
    assert main(["batch", str(root), "-o", str(tmp_path / "b"), "--strict"]) == 1
    text = capsys.readouterr().out
    assert "need review" in text and "1 failed" in text

    clean = tmp_path / "clean"
    clean.mkdir()
    make_t12_xlsx(clean / "t12.xlsx")
    assert main(["batch", str(clean), "-o", str(tmp_path / "c"), "--strict"]) == 0
    assert main(["batch", str(tmp_path / "missing"), "-o", str(tmp_path / "d")]) == 2


def test_summary_text_is_formula_safe(tmp_path):
    root = tmp_path / "in"
    root.mkdir()
    make_t12_xlsx(root / "=cmd.xlsx")
    run_batch(root, tmp_path / "out")
    raw = (tmp_path / "out" / "summary.csv").read_text(encoding="utf-8")
    assert "'=cmd.xlsx" in raw
