"""Shared, durable article queue. This version has no live Dzen transport."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class ArticleQueue:
    def __init__(self, directory: Path, registry: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.directory / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.db_path = self.directory / "queue.sqlite3"
        config = json.loads(Path(registry).read_text(encoding="utf-8-sig"))
        self.account_key = config["account_key"]
        self.channels = {c["project_key"]: c for c in config["channels"]}
        ids = [c["channel_id"] for c in self.channels.values()]
        if len(self.channels) != len(config["channels"]) or len(set(ids)) != len(ids):
            raise ValueError("Duplicate channel configuration")
        if not all(re.fullmatch(r"[0-9a-f]{24}", cid) for cid in ids):
            raise ValueError("Invalid channel ID")
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project_key TEXT NOT NULL,
                channel_id TEXT NOT NULL, account_key TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL,
                publish_at TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                error_code TEXT, error_message TEXT,
                UNIQUE(project_key, idempotency_key))""")
            db.execute("CREATE INDEX IF NOT EXISTS due_jobs ON jobs(status,publish_at)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        # Safe ONLY while the worker performs no external publication.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='QUEUED',updated_at=? WHERE status='PREPARING'", (now(),))

    def upload(self, encoded: str) -> dict:
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > 8 * 1024 * 1024:
                raise ValueError()
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError()
                if source.width * source.height > 16_000_000:
                    raise ValueError()
                source.load()
                image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
                out = io.BytesIO()
                image.save(out, format="PNG")
                data = out.getvalue()
                width, height = image.size
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            raise ServiceError("INVALID_IMAGE", "Нужен корректный PNG, JPEG или WebP до 8 МБ и 16 млн пикселей.") from None
        if len(data) > 16 * 1024 * 1024:
            raise ServiceError("IMAGE_TOO_LARGE", "Изображение после обработки превышает 16 МБ.")
        media_id = hashlib.sha256(data).hexdigest()
        target = self.media_dir / f"{media_id}.png"
        if not target.exists():
            temporary = self.media_dir / f"{media_id}.{uuid.uuid4().hex}.tmp"
            temporary.write_bytes(data)
            temporary.replace(target)
        return {"media_id": media_id, "width": width, "height": height, "mime_type": "image/png"}

    def media_path(self, media_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", media_id):
            raise ServiceError("MEDIA_NOT_FOUND", "Изображение не найдено.", 404)
        path = self.media_dir / f"{media_id}.png"
        if not path.is_file():
            raise ServiceError("MEDIA_NOT_FOUND", "Изображение не найдено.", 404)
        return path

    @staticmethod
    def decode(row):
        if row is None:
            raise ServiceError("JOB_NOT_FOUND", "Задание не найдено.", 404)
        result = dict(row)
        result["article"] = json.loads(result.pop("payload"))
        result.pop("fingerprint", None)
        result.pop("idempotency_key", None)
        result["draft_url"] = None
        result["published_url"] = None
        result["verified"] = False
        return result

    def create(self, article: dict, key: str) -> tuple[dict, bool]:
        article = dict(article)
        if article.get("publish_at"):
            value = datetime.fromisoformat(article["publish_at"])
            if value.tzinfo is None or value.utcoffset() is None:
                raise ServiceError("INVALID_SCHEDULE", "Время требует часового пояса.")
            article["publish_at"] = value.astimezone(timezone.utc).isoformat()
        channel = self.channels.get(article["project_key"])
        if not channel:
            raise ServiceError("UNKNOWN_CHANNEL", "Неизвестный ключ канала.")
        media_ids = [b["media_id"] for b in article["blocks"] if b["type"] == "image"]
        if article.get("cover_media_id"):
            media_ids.append(article["cover_media_id"])
        for mid in media_ids:
            self.media_path(mid)
        if sum(self.media_path(mid).stat().st_size for mid in media_ids) > 32 * 1024 * 1024:
            raise ServiceError("ARTICLE_IMAGES_TOO_LARGE", "Изображения с учётом повторных вставок превышают 32 МБ.")
        if len(set(media_ids)) > 20:
            raise ServiceError("TOO_MANY_IMAGES", "В одной статье допускается до 20 изображений.")
        if sum(len(b.get("text") or "") + sum(map(len, b.get("items") or [])) for b in article["blocks"]) > 60000:
            raise ServiceError("ARTICLE_TOO_LONG", "Текст статьи превышает 60 000 символов.")
        payload = json.dumps(article, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        created = now()
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE project_key=? AND idempotency_key=?", (article["project_key"], key)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "Этот ключ уже использован для другой статьи.", 409)
                return self.decode(existing), False
            db.execute("""INSERT INTO jobs(id,project_key,channel_id,account_key,idempotency_key,
                fingerprint,payload,status,publish_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'QUEUED',?,?,?)""",
                (job_id, article["project_key"], channel["channel_id"], self.account_key,
                 key, fingerprint, payload, article.get("publish_at") or created, created, created))
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self.decode(row), True

    def get(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list(self, limit=50, offset=0):
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"items": [self.decode(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def retry(self, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            self.decode(row)
            if row["status"] != "BLOCKED":
                raise ServiceError("JOB_NOT_RETRYABLE", "Повтор доступен только для заблокированного задания.", 409)
            db.execute("UPDATE jobs SET status='QUEUED',error_code=NULL,error_message=NULL,updated_at=? WHERE id=?", (now(), job_id))
        return self.get(job_id)

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='QUEUED' AND publish_at<=? ORDER BY publish_at,id LIMIT 1", (now(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='PREPARING',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row["id"]))
        return self.get(row["id"])

    def process_one(self):
        job = self.claim()
        if job is None:
            return False
        try:
            self.preview(job["id"])
            code = "DZEN_TRANSPORT_UNAVAILABLE"
            message = "Живой транспорт Дзена не подключён. Статья сохранена локально; загрузки и публикации не было."
        except ServiceError as exc:
            code, message = exc.code, exc.message
        except Exception:
            logger.exception("Preview preparation failed for job %s", job["id"])
            code, message = "PREPARATION_FAILED", "Не удалось подготовить превью. Проверьте локальные файлы сервиса."
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='BLOCKED',error_code=?,error_message=?,updated_at=? WHERE id=?", (code, message, now(), job["id"]))
        return True

    def preview(self, job_id):
        article = self.get(job_id)["article"]
        def image(mid, caption=""):
            data = base64.b64encode(self.media_path(mid).read_bytes()).decode()
            return f'<figure><img src="data:image/png;base64,{data}"><figcaption>{html.escape(caption)}</figcaption></figure>'
        parts = [f"<h1>{html.escape(article['title'])}</h1>"]
        if article.get("cover_media_id"):
            parts.append(image(article["cover_media_id"]))
        for block in article["blocks"]:
            kind = block["type"]
            if kind == "image":
                parts.append(image(block["media_id"], block.get("caption") or ""))
            elif kind == "list":
                parts.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in block["items"]) + "</ul>")
            else:
                tag = {"paragraph": "p", "heading": "h2", "quote": "blockquote"}[kind]
                parts.append(f"<{tag}>{html.escape(block['text'])}</{tag}>")
        return ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
                '<title>Локальное превью статьи</title><style>body{max-width:760px;margin:40px auto;padding:0 20px;font:18px/1.65 system-ui;color:#17212b}img{max-width:100%}figure{margin:24px 0}figcaption{color:#667;font-size:14px}blockquote{border-left:3px solid #456;padding-left:20px}p{white-space:pre-wrap}</style>'
                '<body><p style="color:#956000">Локальное превью. Статья не загружена в Дзен.</p>' + "".join(parts) + '</body></html>')
