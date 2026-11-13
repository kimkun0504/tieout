"""Command line: `tieout clean rent_roll.xlsx -o out/`."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from tieout.export import render_report, write_all
from tieout.mapping import TemplateStore
from tieout.pipeline import clean_file
from tieout.review import Review


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tieout", description="Clean and validate messy rent rolls.")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("clean", help="Clean a rent roll and write CSV, JSON, issues and a report.")
    c.add_argument("file", type=Path)
    c.add_argument("-o", "--out", type=Path, default=Path("out"), help="Output folder (default: out/)")
    c.add_argument("--sheet", help="Sheet name (default: the fullest sheet)")
    c.add_argument("--templates", type=Path, help="Folder of saved column-mapping templates")
    c.add_argument("--save-template", metavar="NAME", help="Save this file's column mapping as a template")
    c.add_argument("--as-of", type=date.fromisoformat, help="Report date (YYYY-MM-DD) for lease-expiry checks")
    c.add_argument("--review", type=Path, help="Reviewer decisions (corrections, overrides) from a review.json file")
    c.add_argument("--strict", action="store_true", help="Exit with code 1 if any error-level issue is left open")

    s = sub.add_parser("serve", help="Run the review web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--data", type=Path, default=Path("tieout-data"), help="Where uploads and reviews are stored")

    args = p.parse_args(argv)
    if args.command == "clean":
        store = TemplateStore(args.templates) if args.templates else None
        review = Review.load(args.review) if args.review else None
        result = clean_file(args.file, sheet=args.sheet, templates=store, as_of=args.as_of, review=review)
        paths = write_all(result, args.out)
        if args.save_template:
            store = store or TemplateStore(args.out / "templates")
            saved = store.save(result.header.headers, result.mappings, args.save_template)
            print(f"Saved template: {saved}")
        print(render_report(result))
        print("Wrote:", ", ".join(str(v) for v in paths.values()))
        return 1 if args.strict and not result.ok else 0
    if args.command == "serve":
        try:
            import uvicorn

            from tieout.api import create_app
        except ImportError:
            print("The web app needs extra packages: pip install 'tieout[server]'", file=sys.stderr)
            return 2
        uvicorn.run(create_app(args.data), host=args.host, port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
