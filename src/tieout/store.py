"""File-based job storage for the web app.

Layout under the data directory:
    jobs/<id>/source.<ext>   the uploaded file, never modified
    jobs/<id>/meta.json      filename, upload time, settings, last summary
    jobs/<id>/review.json    reviewer decisions and audit log
    templates/               saved column-mapping templates

Every write goes to a temp file and is renamed into place, so a crash never
leaves a half-written JSON file. A per-job lock serialises writers.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tieout.ingest import SUPPORTED_SUFFIXES, Grid, read_grid
from tieout.mapping import TemplateStore
from tieout.pipeline import CleanResult, clean_file
from tieout.review import Review, now_iso

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class JobNotFound(KeyError):
    pass


@dataclass
class JobMeta:
    id: str
    filename: str
    suffix: str
    size: int
    sha256: str
    uploaded_at: str
    sheet: str | None = None
    as_of: str | None = None  # ISO date
    last_summary: dict[str, Any] = field(default_factory=dict)
    last_ok: bool | None = None
    updated_at: str = ""
    document_type: str = "rent_roll"  # or "t12"


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def safe_filename(name: str) -> str:
    """Keep a display name without any path parts or control characters."""
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ()&,']", "_", name).strip() or "upload"
    return name[:200]


class JobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.templates = TemplateStore(self.root / "templates")
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # Parsed source sheets. Sources never change, so a grid stays valid for
        # the life of the job; review actions then skip re-reading the workbook.
        self._grids: OrderedDict[tuple[str, str | None], Grid] = OrderedDict()
        self._grids_guard = threading.Lock()
        self.grid_cache_size = 8
        from tieout.llm import mapper_from_env

        self.mapper = mapper_from_env()  # None unless TIEOUT_LLM=1 and an API key are set

    # --- paths and locking ------------------------------------------------------

    def _dir(self, job_id: str) -> Path:
        if not _ID_RE.match(job_id):
            raise JobNotFound(job_id)
        d = self.jobs_dir / job_id
        if not (d / "meta.json").exists():
            raise JobNotFound(job_id)
        return d

    @contextmanager
    def lock(self, job_id: str) -> Iterator[None]:
        with self._locks_guard:
            lk = self._locks.setdefault(job_id, threading.Lock())
        with lk:
            yield

    # --- jobs ---------------------------------------------------------------------

    def create(self, filename: str, content: bytes) -> JobMeta:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported file type {suffix or '(none)'}; use {', '.join(sorted(SUPPORTED_SUFFIXES))}")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        if not content:
            raise ValueError("File is empty")
        job_id = uuid.uuid4().hex
        d = self.jobs_dir / job_id
        d.mkdir()
        (d / f"source{suffix}").write_bytes(content)
        meta = JobMeta(
            job_id, safe_filename(filename), suffix, len(content), hashlib.sha256(content).hexdigest(), now_iso()
        )
        _write_json(d / "meta.json", asdict(meta))
        return meta

    def meta(self, job_id: str) -> JobMeta:
        return JobMeta(**json.loads((self._dir(job_id) / "meta.json").read_text(encoding="utf-8")))

    def save_meta(self, meta: JobMeta) -> None:
        meta.updated_at = now_iso()
        _write_json(self._dir(meta.id) / "meta.json", asdict(meta))

    def list(self) -> list[JobMeta]:
        out = []
        for d in self.jobs_dir.iterdir():
            if (d / "meta.json").exists():
                try:
                    out.append(JobMeta(**json.loads((d / "meta.json").read_text(encoding="utf-8"))))
                except (json.JSONDecodeError, TypeError):
                    continue
        return sorted(out, key=lambda m: m.uploaded_at, reverse=True)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self._dir(job_id))
        with self._grids_guard:
            for key in [k for k in self._grids if k[0] == job_id]:
                del self._grids[key]

    def grid(self, job_id: str) -> Grid:
        meta = self.meta(job_id)
        key = (job_id, meta.sheet)
        with self._grids_guard:
            if key in self._grids:
                self._grids.move_to_end(key)
                return self._grids[key]
        grid = read_grid(self.source_path(job_id), meta.sheet, meta.filename)
        with self._grids_guard:
            self._grids[key] = grid
            while len(self._grids) > self.grid_cache_size:
                self._grids.popitem(last=False)
        return grid

    def source_path(self, job_id: str) -> Path:
        meta = self.meta(job_id)
        return self._dir(job_id) / f"source{meta.suffix}"

    # --- review -------------------------------------------------------------------

    def review(self, job_id: str) -> Review:
        return Review.load(self._dir(job_id) / "review.json")

    def save_review(self, job_id: str, review: Review) -> None:
        review.save(self._dir(job_id) / "review.json")

    # --- running ------------------------------------------------------------------

    def run(self, job_id: str) -> CleanResult:
        """Clean the source with the current review, and record the summary on the job."""
        meta = self.meta(job_id)
        result = clean_file(
            self.source_path(job_id),
            sheet=meta.sheet,
            templates=self.templates,
            mapper=self.mapper,
            as_of=date.fromisoformat(meta.as_of) if meta.as_of else None,
            review=self.review(job_id),
            source_name=meta.filename,
            grid=self.grid(job_id),
        )
        summary = result.summary()
        if summary != meta.last_summary or result.ok != meta.last_ok:
            meta.last_summary, meta.last_ok = summary, result.ok
            self.save_meta(meta)
        return result

    def payload(self, job_id: str) -> dict[str, Any]:
        """The result for any document type, as the API returns it."""
        from tieout import __version__
        from tieout.export import to_payload
        from tieout.t12 import is_t12, read_t12
        from tieout.t12 import to_payload as t12_payload

        grid = self.grid(job_id)
        if is_t12(grid):
            stmt = read_t12(grid)
            review = self.review(job_id)
            for issue in stmt.issues:
                issue.acknowledgment = review.ack_for(issue.id)
            meta = self.meta(job_id)
            s = stmt.summary()
            summary = {
                k: s[k]
                for k in (
                    "period",
                    "months",
                    "line_items",
                    "total_income",
                    "total_expenses",
                    "noi",
                    "errors",
                    "warnings",
                )
            }
            if meta.document_type != "t12" or meta.last_summary != summary or meta.last_ok != stmt.ok:
                meta.document_type, meta.last_summary, meta.last_ok = "t12", summary, stmt.ok
                self.save_meta(meta)
            return {**t12_payload(stmt), "tieout_version": __version__, "review": review.to_dict()}
        return to_payload(self.run(job_id))
