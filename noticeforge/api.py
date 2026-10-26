"""Local review API. No external service is contacted by the demo."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from noticeforge.bom import match_bom
from noticeforge.ingest import MAX_BYTES, InputError, render_page
from noticeforge.model_service import ModelService
from noticeforge.models import BOMRequest, Evidence, ModelDecisionRequest, ModelRunRequest, ReviewRequest
from noticeforge.pipeline import compile_notice
from noticeforge.providers import Provider
from noticeforge.repository import ConflictError, Repository, ReviewError

STATIC = Path(__file__).parent / "static"


def create_app(data_dir: Path | None = None, *, model_provider: Provider | None = None) -> FastAPI:
    repo = Repository(data_dir or Path(os.getenv("NOTICEFORGE_DATA_DIR", "var")))
    model_service = ModelService(repo, model_provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Recover only when this app starts serving, never while importing a factory.
        await run_in_threadpool(repo.interrupt_model_runs)
        try:
            yield
        finally:
            await run_in_threadpool(model_service.close)

    app = FastAPI(title="NoticeForge local review", version="0.1.1", lifespan=lifespan)
    app.state.repo = repo
    app.state.model_service = model_service

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin != str(request.base_url).rstrip("/")
        ):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin mutations are disabled"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    # Validate Host before deriving the same-origin check from it. Explicit names
    # permit a configured reverse proxy without opening the default loopback demo.
    allowed_hosts = ["127.0.0.1", "localhost", "[::1]"]
    allowed_hosts.extend(
        host.strip() for host in os.getenv("NOTICEFORGE_ALLOWED_HOSTS", "").split(",") if host.strip()
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts, www_redirect=False)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Notice not found"})

    @app.exception_handler(InputError)
    async def invalid_input(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ReviewError)
    async def bad_review(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        import shutil

        return {
            "status": "ok",
            "mode": "deterministic-rules",
            "version": "0.1.1",
            "ocr_available": bool(shutil.which("tesseract")),
            "automatic_external_calls": False,
            "remote_model_configured": model_service.remote,
        }

    @app.get("/api/model")
    def model_configuration():
        return model_service.describe()

    @app.get("/api/notices/{notice_id}/model-runs")
    def model_runs(notice_id: str):
        return {"runs": repo.model_runs(notice_id)}

    @app.post("/api/notices/{notice_id}/model-runs", status_code=202)
    def request_model_run(notice_id: str, payload: ModelRunRequest):
        return model_service.start(notice_id, payload.expected_version)

    @app.post("/api/notices/{notice_id}/model-runs/{run_id}/decisions")
    def decide_model_candidate(notice_id: str, run_id: str, payload: ModelDecisionRequest):
        return repo.decide_model_candidate(notice_id, run_id, payload)

    @app.get("/api/notices")
    def list_notices():
        return {
            "notices": [
                {
                    "id": r.id,
                    "notice_id": r.metadata.notice_id.value,
                    "supplier": r.metadata.supplier.value,
                    "title": r.metadata.title.value,
                    "notice_type": r.metadata.notice_type.value,
                    "part_count": len(r.parts),
                    "review_count": sum(p.review_status == "review_required" for p in r.parts),
                    "status": r.status,
                    "created_at": r.created_at,
                    "filename": r.document.filename,
                    "version": r.version,
                    "provenance": r.provenance,
                }
                for r in repo.all_notices()
            ]
        }

    @app.post("/api/notices", status_code=201)
    async def upload(file: UploadFile = File(...), expected_pages: int | None = None):
        data = await file.read(MAX_BYTES + 1)
        record = await run_in_threadpool(compile_notice, data, file.filename or "upload", expected_pages)
        return await run_in_threadpool(repo.save, record, data)

    @app.get("/api/notices/{notice_id}")
    def get_notice(notice_id: str):
        return repo.get(notice_id)

    @app.get("/api/notices/{notice_id}/source")
    def source(notice_id: str):
        record = repo.get(notice_id)
        return Response(
            repo.source(notice_id),
            media_type=record.document.media_type,
            headers={
                "Content-Disposition": f'inline; filename="source{Path(record.document.filename).suffix}"'
            },
        )

    @app.get("/api/notices/{notice_id}/pages/{number}/image")
    def page_image(notice_id: str, number: int):
        record = repo.get(notice_id)
        if record.document.media_type != "application/pdf":
            raise HTTPException(400, "This text notice has no PDF page image")
        return Response(render_page(repo.source(notice_id), number), media_type="image/png")

    @app.get("/api/notices/{notice_id}/audit")
    def audit(notice_id: str):
        return {"events": repo.audit(notice_id)}

    @app.get("/api/notices/{notice_id}/history")
    def history(notice_id: str):
        return repo.history(notice_id)

    @app.post("/api/notices/{notice_id}/reviews")
    def review(notice_id: str, payload: dict):
        # The client may send offsets only; the server always derives the exact quote.
        if isinstance(payload.get("evidence"), dict):
            evidence = payload["evidence"]
            record = repo.get(notice_id)
            try:
                page_number = int(evidence["page"])
                start, end = int(evidence["start"]), int(evidence["end"])
                page = next(p for p in record.document.pages if p.number == page_number)
                if not 0 <= start < end <= len(page.text):
                    raise ValueError()
                payload["evidence"] = Evidence(
                    page=page_number,
                    start=start,
                    end=end,
                    quote=page.text[start:end],
                    method="human-selection",
                ).model_dump()
            except (KeyError, ValueError, StopIteration, TypeError):
                raise ReviewError("Evidence range is outside the source document") from None
        try:
            request = ReviewRequest.model_validate(payload)
        except ValidationError as exc:
            raise ReviewError("Invalid review: " + str(exc.errors()[0]["msg"])) from exc
        return repo.review(notice_id, request)

    @app.post("/api/notices/{notice_id}/bom")
    def bom(notice_id: str, request: BOMRequest):
        return {"matches": match_bom(repo.get(notice_id), request.rows)}

    @app.get("/api/notices/{notice_id}/export")
    def export(notice_id: str, format: str = "json"):
        record = repo.get(notice_id)
        if format == "json":
            # Validated canonical JSON includes unsupported/review findings, never hides them.
            return Response(
                record.model_dump_json(indent=2),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="notice-{notice_id}.json"'},
            )
        if format != "smartpcn":
            raise HTTPException(400, "Choose json or smartpcn")
        from noticeforge.exporters import ExportError, export_smartpcn

        try:
            xml = export_smartpcn(record)
        except ExportError as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(
            xml,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="notice-{notice_id}.xml"'},
        )

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
