"""HTTP API for the review app.

Every mutating endpoint changes only the job's review (never the source file),
re-runs the pipeline and returns the fresh result, so the client always shows
what the server would export.

This is a single-user local tool: it binds to 127.0.0.1 by default and has no
authentication. Put it behind an authenticating proxy before exposing it.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tieout import __version__
from tieout.export import render_report, write_csv, write_issues, write_json, write_jsonl, write_xlsx
from tieout.ingest import UnsupportedFormat
from tieout.schema import RENT_ROLL_FIELDS
from tieout.store import MAX_UPLOAD_BYTES, JobMeta, JobNotFound, JobStore

WEB_DIST = Path(__file__).parent / "web"
log = logging.getLogger("tieout.api")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The app loads nothing from other origins. Inline styles are allowed for
    # computed sizes (chart bars); scripts are not.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
}
MAX_SOURCE_ROWS = 5000


class MappingIn(BaseModel):
    header: str  # override key: header text, or "Rent #2" for a repeated header
    field: str | None


class CorrectionIn(BaseModel):
    source_row: int = Field(ge=1)
    field: str
    value: str | None
    reason: str = Field(min_length=1, max_length=500)


class AckIn(BaseModel):
    issue_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    note: str = Field(min_length=1, max_length=500)


class SettingsIn(BaseModel):
    sheet: str | None = None
    as_of: date | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def _job_view(meta: JobMeta) -> dict[str, Any]:
    return {k: v for k, v in asdict(meta).items() if k != "sha256"} | {"sha256": meta.sha256[:12]}


DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "[::1]")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def allowed_hosts_from_env() -> list[str]:
    raw = os.environ.get("TIEOUT_ALLOWED_HOSTS", "")
    return [h.strip() for h in raw.split(",") if h.strip()] or list(DEFAULT_ALLOWED_HOSTS)


def create_app(data_dir: str | Path = "tieout-data", allowed_hosts: list[str] | None = None) -> FastAPI:
    store = JobStore(data_dir)
    app = FastAPI(title="tieout", version=__version__)
    hosts = allowed_hosts if allowed_hosts is not None else allowed_hosts_from_env()
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    # DNS rebinding: a hostile site resolving its own name to 127.0.0.1 is refused by Host.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def _same_origin_writes(request: Request, call_next: Any) -> Any:
        """Refuse state-changing requests sent by other websites (CSRF).

        Browsers attach Origin to cross-site POSTs, including plain form uploads that
        skip the CORS preflight. Requests without Origin (curl, scripts) are allowed.
        """
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin:
            origin_host = urlsplit(origin).hostname or ""
            if origin_host != request.url.hostname and "*" not in hosts:
                return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def _headers_and_logging(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "%s %s %s %.0fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request_id,
        )
        return response

    @app.exception_handler(JobNotFound)
    async def _not_found(_req: Any, _exc: JobNotFound) -> JSONResponse:
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    def result_response(job_id: str) -> dict[str, Any]:
        payload = store.payload(job_id)
        return {"job": _job_view(store.meta(job_id)), "result": payload}

    def mutate(job_id: str, author: str, fn: Any) -> dict[str, Any]:
        if store.meta(job_id).document_type == "t12":
            raise HTTPException(409, "Corrections and mappings are available for rent rolls only, not T-12 statements.")
        with store.lock(job_id):
            review = store.review(job_id)
            try:
                fn(review, author or "reviewer")
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            store.save_review(job_id, review)
        return result_response(job_id)

    # --- meta ------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/fields")
    def fields() -> list[dict[str, Any]]:
        return [
            {
                "name": f.name,
                "type": f.type.value,
                "description": f.description,
                "required": f.required,
                "output": f.output,
            }
            for f in RENT_ROLL_FIELDS
        ]

    # --- jobs ------------------------------------------------------------------------

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [_job_view(m) for m in store.list()]

    @app.post("/api/jobs", status_code=201)
    async def upload(
        file: Annotated[UploadFile, File()],
        as_of: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        try:
            meta = store.create(file.filename or "upload", content)
        except ValueError as e:
            raise HTTPException(413 if "larger" in str(e) else 415 if "Unsupported" in str(e) else 422, str(e)) from e
        if as_of:
            try:
                meta.as_of = date.fromisoformat(as_of).isoformat()
            except ValueError as e:
                store.delete(meta.id)
                raise HTTPException(422, "as_of must be a date like 2026-11-01") from e
            store.save_meta(meta)
        try:
            return result_response(meta.id)
        except (UnsupportedFormat, ValueError) as e:
            store.delete(meta.id)  # nothing usable was found: don't keep a broken job
            raise HTTPException(422, f"Could not read this file: {e}") from e
        except Exception as e:  # corrupt workbook, zip errors, etc.
            log.exception("Unreadable upload %s (%s)", meta.filename, meta.id)
            store.delete(meta.id)
            raise HTTPException(422, f"Could not read this file ({type(e).__name__}).") from e

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return result_response(job_id)

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> Response:
        with store.lock(job_id):
            store.delete(job_id)
        return Response(status_code=204)

    @app.put("/api/jobs/{job_id}/settings")
    def settings(job_id: str, body: SettingsIn) -> dict[str, Any]:
        """Change sheet or report date. If the new sheet can't be read, nothing changes."""
        with store.lock(job_id):
            meta = store.meta(job_id)
            previous = (meta.sheet, meta.as_of)
            meta.sheet = body.sheet or None
            meta.as_of = body.as_of.isoformat() if body.as_of else None
            store.save_meta(meta)
            try:
                return result_response(job_id)
            except (UnsupportedFormat, ValueError) as e:
                meta.sheet, meta.as_of = previous
                store.save_meta(meta)
                raise HTTPException(422, f"Can't use that sheet: {e}") from e

    @app.get("/api/jobs/{job_id}/source")
    def source(job_id: str) -> dict[str, Any]:
        """The raw sheet, so the UI can show every value in its original context."""
        grid = store.grid(job_id)
        rows = [[_cell_text(v) for v in row] for row in grid.rows[:MAX_SOURCE_ROWS]]
        return {
            "sheet": grid.sheet,
            "rows": rows,
            "truncated": len(grid.rows) > MAX_SOURCE_ROWS,
            "merges": [list(m) for m in grid.merges],
        }

    # --- review actions --------------------------------------------------------------

    @app.put("/api/jobs/{job_id}/mapping")
    def set_mapping(job_id: str, body: MappingIn, x_tieout_user: str = Header("")) -> dict[str, Any]:
        return mutate(job_id, x_tieout_user, lambda r, a: r.override_mapping(body.header, body.field, a))

    @app.post("/api/jobs/{job_id}/mapping/reset")
    def reset_mapping(job_id: str, body: MappingIn, x_tieout_user: str = Header("")) -> dict[str, Any]:
        return mutate(job_id, x_tieout_user, lambda r, a: r.clear_mapping_override(body.header, a))

    @app.post("/api/jobs/{job_id}/corrections")
    def add_correction(job_id: str, body: CorrectionIn, x_tieout_user: str = Header("")) -> dict[str, Any]:
        return mutate(
            job_id, x_tieout_user, lambda r, a: r.correct(body.source_row, body.field, body.value, body.reason, a)
        )

    @app.delete("/api/jobs/{job_id}/corrections")
    def remove_correction(job_id: str, source_row: int, field: str, x_tieout_user: str = Header("")) -> dict[str, Any]:
        def fn(r: Any, a: str) -> None:
            if not r.remove_correction(source_row, field, a):
                raise HTTPException(404, "No such correction")

        return mutate(job_id, x_tieout_user, fn)

    @app.post("/api/jobs/{job_id}/acknowledgments")
    def acknowledge(job_id: str, body: AckIn, x_tieout_user: str = Header("")) -> dict[str, Any]:
        return mutate(job_id, x_tieout_user, lambda r, a: r.acknowledge(body.issue_id, body.note, a))

    @app.delete("/api/jobs/{job_id}/acknowledgments/{issue_id}")
    def unacknowledge(job_id: str, issue_id: str, x_tieout_user: str = Header("")) -> dict[str, Any]:
        return mutate(job_id, x_tieout_user, lambda r, a: r.unacknowledge(issue_id, a))

    @app.post("/api/jobs/{job_id}/template", status_code=201)
    def save_template(job_id: str, body: TemplateIn) -> dict[str, str]:
        if store.meta(job_id).document_type == "t12":
            raise HTTPException(409, "Templates are for rent roll column mappings.")
        result = store.run(job_id)
        path = store.templates.save(result.header.headers, result.mappings, body.name)
        return {"template": path.stem, "name": body.name}

    @app.get("/api/compare")
    def compare_documents(rent_roll: str, t12: str) -> dict[str, Any]:
        """Cross-check a rent roll against a T-12 for the same property."""
        from tieout.compare import compare
        from tieout.t12 import read_t12

        if store.meta(rent_roll).document_type != "rent_roll" or store.meta(t12).document_type != "t12":
            raise HTTPException(422, "Choose one rent roll and one T-12.")
        return compare(store.run(rent_roll), read_t12(store.grid(t12)))

    # --- exports -----------------------------------------------------------------------

    media = {
        "csv": ("text/csv", ".clean.csv"),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".clean.xlsx"),
        "json": ("application/json", ".clean.json"),
        "issues": ("text/csv", ".issues.csv"),
        "report": ("text/markdown", ".report.md"),
        "jsonl": ("application/x-ndjson", ".records.jsonl"),
    }

    @app.get("/api/jobs/{job_id}/export/{fmt}")
    def export(
        job_id: str,
        fmt: Literal["csv", "xlsx", "json", "issues", "report", "jsonl"],
        redact_tenants: bool = False,
    ) -> StreamingResponse:
        import tempfile

        meta = store.meta(job_id)
        stem = re.sub(r"[^\w.-]", "_", Path(meta.filename).stem) or "statement"
        if meta.document_type == "t12":
            return _export_t12(store, job_id, fmt, stem)
        result = store.run(job_id)
        mime, suffix = media[fmt]
        stem = re.sub(r"[^\w.-]", "_", Path(store.meta(job_id).filename).stem) or "rent_roll"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"out{suffix}"
            if fmt == "jsonl":
                write_jsonl(result, path, redact_tenants)
            elif fmt == "report":
                path.write_text(render_report(result))
            else:
                {"csv": write_csv, "xlsx": write_xlsx, "json": write_json, "issues": write_issues}[fmt](result, path)
            data = path.read_bytes()
        return StreamingResponse(
            io.BytesIO(data),
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{stem}{suffix}"'},
        )

    # --- web app -------------------------------------------------------------------------

    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(WEB_DIST / "index.html")

    return app


def _export_t12(store: JobStore, job_id: str, fmt: str, stem: str) -> StreamingResponse:
    import tempfile

    from tieout.t12 import read_t12, write_outputs

    files = {"json": "json", "csv": "csv", "xlsx": "xlsx", "report": "report"}
    if fmt not in files:
        raise HTTPException(422, f"T-12 statements export as {', '.join(files)}.")
    stmt = read_t12(store.grid(job_id))
    with tempfile.TemporaryDirectory() as tmp:
        path = write_outputs(stmt, tmp)[files[fmt]]
        data = path.read_bytes()
        suffix = path.name[len(Path(stmt.file).stem) :]
    mime = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "report": "text/markdown",
    }[fmt]
    return StreamingResponse(
        io.BytesIO(data), media_type=mime, headers={"Content-Disposition": f'attachment; filename="{stem}{suffix}"'}
    )


def _cell_text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat() if not (v.hour or v.minute or v.second) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)
