"""Regressions for local admission, nonblocking uploads and durable lifecycle state."""

import asyncio
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread, local

import pytest
from fastapi.testclient import TestClient

from noticeforge.api import create_app
from noticeforge.models import ReviewRequest
from noticeforge.pipeline import compile_notice
from noticeforge.providers import FixtureProvider
from noticeforge.repository import ConflictError, Repository, ReviewError

SOURCE = b"""Notice ID: OWNED-PCN-1
Supplier: Owned Lifecycle Company
Notice type: PCN
Issue date: 2026-10-01
Part number | Effective change
RX-01A | 2027-01-01
"""


def test_importing_api_does_not_change_unselected_database(tmp_path):
    default_root = tmp_path / "default"
    repo = Repository(default_root)
    record = repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    repo.start_model_run(record.id, 1, {"provider": "fixture-offline", "model": "fixture-json-v1"}, "a" * 64)
    env = {**os.environ, "NOTICEFORGE_DATA_DIR": str(default_root), "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-c", "import noticeforge.api"], check=True, env=env)
    assert repo.model_runs(record.id)[0]["status"] == "queued"


@pytest.mark.parametrize("operation", ["compile", "save"])
def test_upload_keeps_event_loop_available_during_blocking_work(tmp_path, monkeypatch, operation):
    import noticeforge.api as api

    app = create_app(tmp_path)
    entered, release = Event(), Event()
    original = api.compile_notice if operation == "compile" else app.state.repo.save

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(timeout=1)
        return original(*args, **kwargs)

    if operation == "compile":
        monkeypatch.setattr(api, "compile_notice", blocked)
    else:
        monkeypatch.setattr(app.state.repo, "save", blocked)

    class Upload:
        filename = "owned.txt"

        async def read(self, limit):
            return SOURCE[:limit]

    async def exercise():
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", None) == "/api/notices" and "POST" in route.methods
        )
        pending = asyncio.create_task(endpoint(Upload()))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            assert not pending.done(), "Upload work blocked the event loop until completion"
        finally:
            release.set()
            record = await pending
        assert app.state.repo.get(record.id).parts[0].raw_identifier.value == "RX-01A"

    asyncio.run(exercise())


@pytest.mark.parametrize("authority", ["localhost:8877", "127.0.0.1:8877", "[::1]:8877"])
def test_default_local_authorities_remain_usable(tmp_path, authority):
    with TestClient(create_app(tmp_path), base_url=f"http://{authority}") as client:
        assert client.get("/api/health").status_code == 200
        assert (
            client.post(
                "/api/notices",
                headers={"Origin": f"http://{authority}"},
                files={"file": ("owned.txt", SOURCE)},
            ).status_code
            == 201
        )


def test_matching_untrusted_host_and_origin_cannot_read_or_mutate(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://attacker.example:8877") as client:
        assert client.get("/api/notices").status_code == 400
        assert (
            client.post(
                "/api/notices",
                headers={"Origin": "http://attacker.example:8877"},
                files={"file": ("owned.txt", SOURCE)},
            ).status_code
            == 400
        )
    assert app.state.repo.all_notices() == []


def test_explicit_proxy_host_keeps_same_origin_protection(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTICEFORGE_ALLOWED_HOSTS", "notices.example")
    with TestClient(create_app(tmp_path), base_url="https://notices.example") as client:
        assert (
            client.post(
                "/api/notices",
                headers={"Origin": "https://notices.example"},
                files={"file": ("owned.txt", SOURCE)},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/notices",
                headers={"Origin": "https://other.example"},
                files={"file": ("other.txt", SOURCE)},
            ).status_code
            == 403
        )


def test_unused_app_does_not_interrupt_model_work(tmp_path):
    repo = Repository(tmp_path)
    record = repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    repo.start_model_run(record.id, 1, {"provider": "fixture-offline", "model": "fixture-json-v1"}, "a" * 64)
    create_app(tmp_path)
    assert repo.model_runs(record.id)[0]["status"] == "queued"


def test_lifespan_recovers_pending_jobs_then_closes_model_service(tmp_path):
    app = create_app(tmp_path, model_provider=FixtureProvider())
    repo = app.state.repo
    record = repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    repo.start_model_run(record.id, 1, {"provider": "fixture-offline", "model": "fixture-json-v1"}, "a" * 64)
    try:
        with TestClient(app, base_url="http://127.0.0.1"):
            assert repo.model_runs(record.id)[0]["status"] == "error"
        before = repo.model_runs(record.id)
        with pytest.raises(ReviewError, match="shut down"):
            app.state.model_service.start(record.id, record.version)
        assert repo.model_runs(record.id) == before
    finally:
        app.state.model_service.close()


def test_shutdown_prevents_new_model_work_without_persisting_a_request(tmp_path):
    app = create_app(tmp_path, model_provider=FixtureProvider())
    record = app.state.repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    try:
        with TestClient(app, base_url="http://127.0.0.1"):
            pass
        with pytest.raises(ReviewError, match="shut down"):
            app.state.model_service.start(record.id, record.version)
        assert app.state.repo.model_runs(record.id) == []
    finally:
        app.state.model_service.close()


def test_close_waits_for_running_model_work_to_be_persisted(tmp_path):
    entered, release = Event(), Event()

    class WaitingProvider(FixtureProvider):
        def generate(self, request):
            entered.set()
            release.wait(timeout=5)
            return super().generate(request)

    app = create_app(tmp_path, model_provider=WaitingProvider())
    record = app.state.repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    app.state.model_service.start(record.id, record.version)
    closer = Thread(target=app.state.model_service.close)
    try:
        assert entered.wait(timeout=2)
        closer.start()
        closer.join(timeout=0.05)
        assert closer.is_alive(), "Model close returned before its running result was persisted"
    finally:
        release.set()
        closer.join(timeout=5)
        app.state.model_service.close()
    assert not closer.is_alive()
    assert app.state.repo.model_runs(record.id)[0]["status"] == "ok"


def test_conflicting_page_count_reimport_cannot_hide_missing_pages_or_erase_reviews(tmp_path):
    repo = Repository(tmp_path)
    original = repo.save(compile_notice(SOURCE, "owned.txt"), SOURCE)
    reviewed = repo.review(
        original.id,
        ReviewRequest(
            field_path="parts.0.raw_identifier",
            action="accept",
            reason="Checked the exact source identifier",
            reviewer="Engineer",
            expected_version=1,
        ),
    )
    conflicting = compile_notice(SOURCE, "owned.txt", expected_pages=2)
    assert conflicting.status == "incomplete"
    with pytest.raises(ConflictError, match="page count"):
        repo.save(conflicting, SOURCE)
    assert repo.get(original.id) == reviewed
    assert repo.original(original.id) == original
    assert len(repo.audit(original.id)) == 2


def test_native_pdf_parse_serializes_rendering_without_blocking_text(monkeypatch):
    from noticeforge import ingest

    source = (
        Path(__file__).resolve().parents[1] / "fixtures/development/aster-discontinuation.pdf"
    ).read_bytes()
    parsing, render_requested, native_render, release = Event(), Event(), Event(), Event()
    role = local()
    original_open = ingest.pymupdf.open
    original_text = ingest.pymupdf.Page.get_text

    def observed_open(*args, **kwargs):
        if getattr(role, "name", None) == "render":
            native_render.set()
        return original_open(*args, **kwargs)

    def paused_text(page, *args, **kwargs):
        if getattr(role, "name", None) == "parse":
            parsing.set()
            release.wait(timeout=5)
        return original_text(page, *args, **kwargs)

    def parse():
        role.name = "parse"
        return compile_notice(source, "owned.pdf")

    def render():
        role.name = "render"
        render_requested.set()
        return ingest.render_page(source, 1)

    monkeypatch.setattr(ingest.pymupdf, "open", observed_open)
    monkeypatch.setattr(ingest.pymupdf.Page, "get_text", paused_text)
    with ThreadPoolExecutor(max_workers=3) as pool:
        parsed = pool.submit(parse)
        try:
            assert parsing.wait(timeout=2)
            rendered = pool.submit(render)
            assert render_requested.wait(timeout=2)
            text = pool.submit(compile_notice, SOURCE, "owned.txt").result(timeout=1)
            assert text.parts[0].raw_identifier.value == "RX-01A"
            assert not native_render.wait(timeout=0.1), "Rendering entered native PDF work during parsing"
        finally:
            release.set()
        record, image = parsed.result(timeout=5), rendered.result(timeout=5)
    parts = {part.raw_identifier.value: part for part in record.parts}
    assert parts["00128-Q1"].dates[0].value == "2027-03-31"
    assert record.document.complete
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
