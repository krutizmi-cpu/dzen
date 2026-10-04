"""Loopback API for a shared article queue, with a disabled live transport."""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from product_kb.dzen_autopost import ArticleQueue, ServiceError
from product_kb.dzen_integration import adapter_contract, integration_status

ROOT = Path(__file__).resolve().parents[1]


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["paragraph", "heading", "image", "quote", "list"]
    text: str | None = Field(default=None, max_length=60000)
    media_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    caption: str | None = Field(default=None, max_length=1000)
    items: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if self.type == "image":
            if not self.media_id or self.text is not None or self.items is not None:
                raise ValueError("Image block requires media_id")
        elif self.type == "list":
            if not self.items or any(not x.strip() for x in self.items) or self.text is not None or self.media_id is not None or self.caption is not None:
                raise ValueError("List requires nonempty items")
        elif not self.text or not self.text.strip() or self.media_id is not None or self.items is not None or self.caption is not None:
            raise ValueError("Text block requires text")
        return self


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=140)
    blocks: list[Block] = Field(min_length=1, max_length=150)
    cover_media_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mode: Literal["draft", "publish"] = "draft"
    publish_at: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if not self.title.strip():
            raise ValueError("Title must not be blank")
        if self.publish_at:
            if self.publish_at.tzinfo is None or self.publish_at.utcoffset() is None:
                raise ValueError("publish_at requires a timezone")
            self.publish_at = self.publish_at.astimezone(timezone.utc)
        return self


class Media(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_base64: str = Field(min_length=1, max_length=12_000_000)


def runtime_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "DzenAutopostService"


def create_app(directory: Path | None = None, registry: Path | None = None,
               token: str | None = None, worker: bool = True,
               root_path: str = "", allowed_hosts: list[str] | None = None) -> FastAPI:
    if not re.fullmatch(r"(?:/[a-zA-Z0-9_-]+)*", root_path):
        raise ValueError("Invalid reverse-proxy root path")
    directory = directory or runtime_directory()
    queue = ArticleQueue(directory, registry or ROOT / "config" / "dzen-channels.json")
    token_path = directory / "api-token.txt"
    if token is None:
        if not token_path.exists():
            with token_path.open("x", encoding="utf-8") as stream:
                if os.name != "nt":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(secrets.token_urlsafe(36))
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ValueError("Invalid local API token")

    async def work():
        while True:
            worked = await asyncio.to_thread(queue.process_one)
            await asyncio.sleep(0.05 if worked else 1)

    @asynccontextmanager
    async def lifespan(app):
        queue.recover()
        task = asyncio.create_task(work()) if worker else None
        app.state.worker_task = task
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Dzen article queue", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, root_path=root_path)
    app.state.queue = queue
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost", "testserver"])

    def authorized(authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not authorization or not authorization.startswith("Bearer ") or not secrets.compare_digest(supplied.encode(), token.encode()):
            raise ServiceError("UNAUTHORIZED", "Нужен Bearer-токен локального сервиса.", 401)

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        if request.method == "POST":
            size = request.headers.get("content-length", "")
            if not size.isdigit():
                return JSONResponse({"error": {"code": "LENGTH_REQUIRED", "message": "Нужен Content-Length."}}, status_code=411)
            if int(size) > 13_000_000:
                return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "Запрос превышает 13 МБ."}}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "Проверьте поля запроса.",
                             "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}}, status_code=422)

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        page = (Path(__file__).with_name("dzen_autopost_dashboard.html")).read_text(encoding="utf-8")
        page = page.replace("const apiBase='/api/v1/';", "const apiBase=" + json.dumps(root_path + "/api/v1/") + ";")
        return HTMLResponse(page,
                            headers={"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"})

    @app.get("/health")
    def health():
        task = getattr(app.state, "worker_task", None)
        if task is not None and task.done():
            return JSONResponse({"status": "worker_failed", "live_ready": False, "transport": "disabled"}, status_code=503)
        return {"status": "ok", "live_ready": False, "transport": "disabled", "channels": len(queue.channels)}

    auth = [Depends(authorized)]

    @app.get("/api/v1/integration", dependencies=auth)
    def integration():
        return integration_status(queue.account_key, list(queue.channels.values()))

    @app.get("/api/v1/integration/contract", dependencies=auth)
    def contract():
        return adapter_contract()

    @app.get("/api/v1/channels", dependencies=auth)
    def channels():
        return {"account_key": queue.account_key, "items": list(queue.channels.values()), "live_verified": False}

    @app.post("/api/v1/media", dependencies=auth, status_code=201)
    def upload(media: Media):
        return queue.upload(media.data_base64)

    @app.get("/api/v1/media/{media_id}", dependencies=auth)
    def media(media_id: str):
        return FileResponse(queue.media_path(media_id), media_type="image/png")

    @app.post("/api/v1/jobs", dependencies=auth)
    def create(article: Article, idempotency_key: str = Header(min_length=1, max_length=128)):
        job, created = queue.create(article.model_dump(mode="json", exclude_none=True), idempotency_key)
        return JSONResponse(job, status_code=201 if created else 200)

    @app.get("/api/v1/jobs", dependencies=auth)
    def jobs(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return queue.list(limit, offset)

    @app.get("/api/v1/jobs/{job_id}", dependencies=auth)
    def job(job_id: str):
        return queue.get(job_id)

    @app.post("/api/v1/jobs/{job_id}/retry", dependencies=auth)
    def retry(job_id: str):
        return queue.retry(job_id)

    @app.get("/api/v1/jobs/{job_id}/preview", dependencies=auth, response_class=HTMLResponse)
    def preview(job_id: str):
        return HTMLResponse(queue.preview(job_id), headers={"Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'"})

    @app.get("/api/v1/openapi.json", dependencies=auth)
    def schema():
        return app.openapi()

    return app
