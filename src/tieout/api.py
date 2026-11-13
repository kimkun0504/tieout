"""HTTP API for the review app.

Every mutating endpoint changes only the job's review (never the source file),
re-runs the pipeline and returns the fresh result, so the client always shows
what the server would export.

This is a single-user local tool: it binds to 127.0.0.1 by default and has no
authentication. Put it behind an authenticating proxy before exposing it.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tieout import __version__
from tieout.export import render_report, to_payload, write_csv, write_issues, write_json, write_xlsx
from tieout.ingest import UnsupportedFormat, read_grid
from tieout.schema import RENT_ROLL_FIELDS
from tieout.store import MAX_UPLOAD_BYTES, JobMeta, JobNotFound, JobStore

WEB_DIST = Path(__file__).parent / "web"
MAX_SOURCE_ROWS = 5000


class MappingIn(BaseModel):
    header: str
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


def create_app(data_dir: str | Path = "tieout-data") -> FastAPI:
    store = JobStore(data_dir)
    app = FastAPI(title="tieout", version=__version__)

    @app.exception_handler(JobNotFound)
    async def _not_found(_req: Any, _exc: JobNotFound) -> JSONResponse:
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    def result_response(job_id: str) -> dict[str, Any]:
        result = store.run(job_id)
        return {"job": _job_view(store.meta(job_id)), "result": to_payload(result)}

    def mutate(job_id: str, author: str, fn: Any) -> dict[str, Any]:
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
        with store.lock(job_id):
            meta = store.meta(job_id)
            meta.sheet = body.sheet or None
            meta.as_of = body.as_of.isoformat() if body.as_of else None
            store.save_meta(meta)
        try:
            return result_response(job_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/jobs/{job_id}/source")
    def source(job_id: str) -> dict[str, Any]:
        """The raw sheet, so the UI can show every value in its original context."""
        meta = store.meta(job_id)
        grid = read_grid(store.source_path(job_id), meta.sheet)
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
        result = store.run(job_id)
        path = store.templates.save(result.header.headers, result.mappings, body.name)
        return {"template": path.stem, "name": body.name}

    # --- exports -----------------------------------------------------------------------

    media = {
        "csv": ("text/csv", ".clean.csv"),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".clean.xlsx"),
        "json": ("application/json", ".clean.json"),
        "issues": ("text/csv", ".issues.csv"),
        "report": ("text/markdown", ".report.md"),
    }

    @app.get("/api/jobs/{job_id}/export/{fmt}")
    def export(job_id: str, fmt: Literal["csv", "xlsx", "json", "issues", "report"]) -> StreamingResponse:
        import tempfile

        result = store.run(job_id)
        mime, suffix = media[fmt]
        stem = re.sub(r"[^\w.-]", "_", Path(store.meta(job_id).filename).stem) or "rent_roll"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"out{suffix}"
            {"csv": write_csv, "xlsx": write_xlsx, "json": write_json, "issues": write_issues}.get(
                fmt, lambda r, p: p.write_text(render_report(r))
            )(result, path)
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


def _cell_text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat() if not (v.hour or v.minute or v.second) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)
