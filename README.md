# tieout

Turns messy rent rolls (Excel, CSV, PDF) into clean, validated, AI-ready data, with every value traced to its source.

Every property-management system exports rent rolls differently: title rows above the table, headers split over two rows, building sections, subtotal rows, money stored as text, ALL-CAPS names, "VACANT" typed into the tenant column. tieout reads those files, maps them onto one canonical schema, and checks that the numbers **tie out**: every subtotal and grand total must equal the sum of the rows it covers.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python examples/make_samples.py                      # writes two synthetic rent rolls
tieout clean examples/data/maple_court.xlsx          # clean file: PASS
tieout clean examples/data/flat_export.csv --as-of 2026-11-01   # planted problems: NEEDS REVIEW
pytest
```

Each run writes four files to `out/`:

| File | What it holds |
| --- | --- |
| `<name>.clean.csv` | One row per unit in the canonical schema, plus section and source row |
| `<name>.clean.json` | Same rows; every value carries its raw text and source cell (e.g. `Rent Roll!F8`), plus mappings, totals and issues |
| `<name>.issues.csv` | Errors, warnings and info, with row and cell references |
| `<name>.report.md` | Human-readable summary: occupancy, rent totals, column mapping, issues |

## How it works

```
file ──> ingest ──> detect header ──> map columns ──> normalize ──> validate ──> export
         (xlsx/csv)  (title rows,      (template →      (money, dates,  (tie-out,
                      2-row headers,    synonyms →       status, names)  duplicates,
                      sections, totals) optional LLM)                    lease logic)
```

| Module | Responsibility |
| --- | --- |
| `ingest.py` | Read xlsx/csv into a grid; expand merged cells; remember sheet, row and column of every value |
| `detect.py` | Find the header row (alone or joined with the row above); classify rows as data, total, section, repeated header or note |
| `mapping.py` | Map headers to schema fields via saved templates, then synonyms/fuzzy match, then an optional `HeaderMapper` (e.g. an LLM) |
| `normalize.py` | Parse money (`$1,250.00`, `(100)`), numbers, dates (Excel serials, text), status words; tidy ALL-CAPS names |
| `validate.py` | Rules: totals tie out, required columns, duplicate units, reversed lease dates, vacant-with-rent, rent far from market, expired leases |
| `export.py` | CSV, JSON with provenance, issues CSV, Markdown report |
| `schema.py` | The canonical rent roll fields and their synonyms |

### Templates

Once a reviewer has confirmed how a source system's export maps to the schema, save it:

```bash
tieout clean file.xlsx --templates templates/ --save-template "maple-court-export"
```

The next file with the same header layout maps from the template with no guessing.

## Canonical schema

`unit`, `unit_type`, `sqft`, `tenant`, `status` (occupied / vacant / notice / model / down), `market_rent`, `current_rent`, `deposit`, `move_in`, `lease_start`, `lease_end`.

## Roadmap

- [ ] PDF input via [Docling](https://github.com/docling-project/docling): parse tables, then reuse this pipeline
- [ ] Multi-line charge rows (rent, parking, pet fees listed under one unit)
- [ ] LLM `HeaderMapper` implementation for unseen layouts, capped below rule confidence
- [ ] T-12 operating statement support
- [ ] Review UI: grid with low-confidence cells highlighted and click-through to source
- [ ] Export to underwriting templates (.xlsx) and RAG-ready JSONL chunks

## Data

The sample files in `tests/samples.py` are synthetic: all names and numbers are invented. Don't commit real rent rolls; `out/` and `data/private/` are git-ignored.
