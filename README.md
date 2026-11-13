# tieout

Turns messy rent rolls and T-12 operating statements (Excel .xlsx and .xls, CSV, PDF) into clean, validated, AI-ready data, with every value traced to its source.

Every property management system exports rent rolls differently: title rows above the table, headers split over two rows, building sections, subtotals, charge lines under each unit, money stored as text, "VACANT" typed into the tenant column. tieout reads those files, maps them onto one schema, and checks that the numbers **tie out**: every subtotal and total in the file must equal the sum of the units it covers. A reviewer resolves what's left (correct a value, or accept an issue with a note) and exports data they can trust.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Web app (build the UI once)
cd web && npm ci && npm run build && cd ..
tieout serve                      # http://127.0.0.1:8000

# Command line
python examples/make_samples.py
tieout clean examples/data/maple_court.xlsx                       # PASS
tieout clean examples/data/flat_export.csv --as-of 2026-11-01     # NEEDS REVIEW

# A whole folder (rent rolls and T-12s); writes out/<file>/… and out/summary.csv
tieout batch examples/data -o out --strict                        # exit 1 unless every file ties out
```

`tieout batch` skips Excel lock files (`~$…`) and hidden files, keeps going past a file it can't read
(the summary records the error), and gives each file its own folder, so `2024/t12.xlsx` and `2025/t12.xlsx`
don't overwrite each other.

Or with Docker:

```bash
docker build -t tieout .
docker run -p 8000:8000 -v tieout-data:/data tieout
```

## The review app

| Part | What it does |
| --- | --- |
| Totals strip | Each reported total next to what its units add up to; the gap is called out |
| Stacking plan | Every unit as a tile, shaded by status, marked where problems are |
| Monthly figures | Physical and economic occupancy, gross potential rent, loss to lease, vacancy loss, concessions, unit mix, 12-month lease expirations |
| To review | Open errors and warnings; accept with a required note, or reopen |
| Units | Cleaned table; derived cells tinted blue, corrections amber, problems underlined |
| Inspector | For any value: raw text, source cell, how it was derived, its problem, and a correction form that requires a reason |
| Original file | The sheet exactly as uploaded, with the selected cell highlighted |
| Column mapping | Change how a column is read; save the mapping as a template for that export format |
| Changes | Who corrected, accepted or remapped what, and when |

Exports: Excel workbook (Rent Roll, Issues, Summary), CSV, JSON with full provenance, issues CSV, Markdown report, and **records for AI** (JSONL): one record per unit with plain-sentence text for embedding, typed fields, and metadata tracing every value to its cell, with an option to remove tenant names. The command line also writes a [Frictionless Data Package](https://datapackage.org/) (`*.datapackage.json`) describing both CSVs with typed fields, so pandas, DuckDB and data catalogs load them without guessing types. All text files are UTF-8.

The app is a single-user local tool: it binds to `127.0.0.1` and has no authentication. Put it behind an authenticating proxy before exposing it to a network. Built-in protections: it answers only to known host names (`TIEOUT_ALLOWED_HOSTS`, default `localhost,127.0.0.1`) against DNS rebinding, refuses state-changing requests from other websites (CSRF), sends a strict Content-Security-Policy and related headers, limits uploads to 25 MB, refuses zip-bomb workbooks, and writes CSV/Excel exports so cell text can never run as a formula.

## How it works

```
file ─> ingest ─> detect header ─> map columns ─> classify rows ─> build rows ─> apply review ─> validate ─> export
        xlsx/csv   title rows,      template >      data, charge,    parse values,   corrections,   tie-out,
        merges,    2-row headers    synonyms >      total, section,  roll up         overrides,     duplicates,
        formulas                    reviewer        repeated header, charge lines    accepted       lease logic,
                                    overrides       page noise                       issues         metrics
```

| Module | Responsibility |
| --- | --- |
| `pdf.py` | Rebuild tables from text-based PDF exports, using the header line's columns as anchors; each row keeps its page |
| `legacy.py` | Read `.xls` by its bytes, not its name: Excel 97-2003 workbooks, HTML tables saved as .xls by "Export to Excel" buttons, Excel 2003 XML, or an .xlsx misnamed .xls |
| `ingest.py` | Read xlsx/xls/csv/pdf into a grid that remembers sheet, row and column for every value; keeps merge ranges; finds formulas with no saved result |
| `detect.py` | Find the header (alone or joined with the row above); classify rows as data, charge line, total, section, repeated header or note |
| `mapping.py` | Map headers to fields via saved templates, then synonyms and fuzzy matching (qualifiers like SF, annual, prior block wrong matches), then an optional pluggable mapper |
| `normalize.py` | Strict parsers: money, numbers, dates, status words, vacancy markers, names. Anything ambiguous is flagged, never guessed |
| `pipeline.py` | Run the stages; roll charge lines up into rent, concessions and other charges; apply reviewer decisions; infer missing status from evidence |
| `review.py` | Reviewer decisions stored beside the untouched source, re-applied on every run, with an audit log |
| `validate.py` | Rules: totals tie out, required columns, duplicates, reversed lease dates, vacant with rent, rent far from market, expired leases |
| `metrics.py` | Standard rent roll analytics |
| `t12.py` | T-12 statements: month header detection, line items and sections, across/down/through tie-outs, categories, tidy export |
| `llm.py` | Optional Claude fallback for unfamiliar headers (sends header names and value shapes only) |
| `export.py` | Excel, CSV (formula-injection safe), JSON payload, issues, report |
| `store.py`, `api.py` | File-based job storage with atomic writes; FastAPI endpoints for the web app |
| `web/` | React + TypeScript + Tailwind review app |

### Principles

- **Never guess a number.** A value that doesn't clearly match its type is left blank and flagged. "Paid thru 10/31" is not $1,031.
- **The source is never modified.** Corrections, mapping overrides and accepted issues live in `review.json` beside it and are re-applied on every run, so output is reproducible and every change is attributable.
- **Everything is traceable.** Each value carries its raw text and cell; rolled-up values carry every cell they came from.
- **Money is exact.** Decimal arithmetic, half-up rounding, decimal strings in JSON.

## T-12 operating statements

Upload or `tieout clean` a T-12 and it is recognised by its row of month columns. tieout checks it three ways:

| Check | Meaning |
| --- | --- |
| Across | Each line's 12 months add up to its Total column |
| Down | Each subtotal equals its lines, month by month |
| Through | Net operating income equals income minus expenses, month by month |

**Rent roll vs T-12:** pick the property's rent roll from the T-12 screen (or call `/api/compare`) to check market rent against gross potential rent, rent in place against net rental income, and economic occupancy on both, all against the statement's last month. Within 2% is consistent; beyond 5% needs explaining.

Line items are mapped to standard underwriting categories (gross potential rent, loss to lease, vacancy, concessions, other income, payroll, repairs and maintenance, utilities, management fee, taxes, insurance...) within their section; anything unmatched is listed rather than guessed. Exports include a tidy CSV with one row per line item per month and the source cell of every amount.

## Optional: Claude for unfamiliar headers

When a column header matches no rule, tieout can ask Claude to place it:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
tieout clean file.xlsx --llm          # CLI
TIEOUT_LLM=1 tieout serve             # web app
```

Only header names and the *shape* of sample values ("money-like", "date-like", "short text") are sent, never the values, so tenant names and amounts stay on your machine. Suggestions are capped below rule confidence and shown for review; any API error means no suggestion. Save the confirmed mapping as a template and the model is never asked about that export format again. The default model is `claude-haiku-5-5` (override with `TIEOUT_LLM_MODEL`).

## Canonical schema

`unit`, `unit_type`, `sqft`, `tenant`, `status` (occupied / vacant / notice / model / down), `market_rent`, `current_rent`, `annual_rent`, `concessions`, `other_charges`, `total_charges`, `deposit`, `move_in`, `lease_start`, `lease_end`. Charge-line layouts also read `charge_code` and `charge_amount`.

## Development

```bash
pytest                         # Python tests
ruff check src tests && ruff format --check src tests
mypy                           # strict
cd web && npm test && npm run typecheck && npm run lint
cd web && npm run dev          # UI on :5173, proxying /api to tieout serve on :8000
```

CI runs all of the above on Python 3.10 to 3.13, builds the web app and the Docker image, and smoke-tests the container.

## Roadmap

- [ ] OCR for scanned PDFs (text-based PDFs are supported)
- [ ] Reviewer corrections for T-12 statements (rent rolls have them)
- [ ] Multi-user: authentication, roles, shared templates
- [ ] Export to common underwriting templates and RAG-ready JSONL

## Data

The sample files in `tests/samples.py` are synthetic: all names and numbers are invented. Don't commit real rent rolls; `out/`, `data/private/` and `tieout-data/` are git-ignored.
