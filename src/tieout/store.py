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
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from tieout.ingest import SUPPORTED_SUFFIXES
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


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
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
        meta = JobMeta(job_id, safe_filename(filename), suffix, len(content), hashlib.sha256(content).hexdigest(), now_iso())
        _write_json(d / "meta.json", asdict(meta))
        return meta

    def meta(self, job_id: str) -> JobMeta:
        return JobMeta(**json.loads((self._dir(job_id) / "meta.json").read_text()))

    def save_meta(self, meta: JobMeta) -> None:
        meta.updated_at = now_iso()
        _write_json(self._dir(meta.id) / "meta.json", asdict(meta))

    def list(self) -> list[JobMeta]:
        out = []
        for d in self.jobs_dir.iterdir():
            if (d / "meta.json").exists():
                try:
                    out.append(JobMeta(**json.loads((d / "meta.json").read_text())))
                except (json.JSONDecodeError, TypeError):
                    continue
        return sorted(out, key=lambda m: m.uploaded_at, reverse=True)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self._dir(job_id))

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
            as_of=date.fromisoformat(meta.as_of) if meta.as_of else None,
            review=self.review(job_id),
        )
        summary = result.summary()
        if summary != meta.last_summary or result.ok != meta.last_ok:
            meta.last_summary, meta.last_ok = summary, result.ok
            self.save_meta(meta)
        return result
