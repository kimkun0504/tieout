# Changelog

All notable changes to tieout. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Inputs
- `.xls` files are read by their bytes: Excel 97-2003 workbooks, HTML tables saved as `.xls` by "Export to Excel" buttons, Excel 2003 XML (parsed with defusedxml), or an `.xlsx` with the old extension.
- Text-based PDFs, with columns rebuilt from the header line and wrapped cells joined. Scanned PDFs are refused with a clear message.
- UTF-16 "Unicode Text" exports and stray NUL bytes.
- The report date is read from the title rows ("As of 10/31/2026", Yardi's "As Of = …", "Report Date: …"). Printed/run dates are ignored. A date the reviewer sets wins, with a warning when it differs from the file.

### Accuracy
- Every subtotal and total is tied out against the units it covers, including charge-line layouts.
- Footer statistics ("Total Units 120", "Occupancy 95.0%") are checked against the units read instead of being read as units. Occupancy is compared at the precision it was printed with.
- Future and applicant lease rows ("Future Residents/Applicants") get status `future`: kept in the output, left out of unit counts, occupancy, rent and duplicate checks.
- Commercial rent rolls: rent per square foot (annual, or monthly converted ×12) is checked against area × rent. Rates are never tied out as sums.
- Unit codes spelled differently ("101", "Apt 101", "0101") are flagged as possible duplicates.
- Excel's accounting dash ("$ -") reads as empty, like "-".
- Cross-checks: annual vs monthly rent, rent column vs rent charge lines, rent per square foot outliers within a unit type.

### T-12 operating statements
- Recognised by their month columns; across, down and through checks with a $1 tolerance; nested subtotals; capex below NOI.
- Line items are categorised (now including plain "Rent", CAM recoveries, supplies, fuel, bank charges and more).
- Reviewers can accept T-12 issues with a note, as for rent rolls.
- Rent roll vs T-12 cross-check (2% / 5% bands).

### Outputs
- Clean CSV, JSON with provenance, Excel workbook, issues CSV, Markdown report, JSONL records for AI (optionally without tenant names).
- A Frictionless Data Package (`*.datapackage.json`) describes both CSVs with types.
- All text files are UTF-8; JSON and JSONL keep non-ASCII characters readable.
- CSV and Excel outputs are safe from formula injection.

### Command line
- `tieout batch FOLDER` cleans every rent roll and T-12 in a folder (optionally recursive) and writes `summary.csv`. An unreadable file is recorded and the batch continues. `--strict` exits 1 unless every file ties out.

### Review app
- Upload several files at once; each shows whether it ties out. Re-uploads of identical files are marked.
- Totals strip grouped by total row, plus the report's footer figures.
- Report date shows where it came from.
- Units table filters by status.
- Stacking plan, inspector with source cell, corrections with required reasons, accept-with-note, audit log, keyboard review (j/k), WCAG AA contrast.

### Security
- Local server protected from DNS rebinding (allowed hosts) and cross-site writes (same-origin check); security headers including a CSP.
- Upload size limit, zip-bomb guard, XML entity attacks refused.
