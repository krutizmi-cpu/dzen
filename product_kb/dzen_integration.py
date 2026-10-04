"""Read-only integration contract. No login, credentials or remote transport."""
from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

CONTRACT_VERSION = "1.0"


class ConnectionState(TypedDict):
    status: Literal["NOT_CONFIGURED", "DISCONNECTED", "EXPIRED", "READY", "ERROR"]
    checked_at: str | None
    verified_channel_ids: list[str]


class SubmissionReceipt(TypedDict):
    status: Literal["DRAFT_VERIFIED", "PUBLISHED_VERIFIED", "FAILED", "UNCERTAIN"]
    channel_id: str
    publication_url: str | None
    verified_at: str | None


class ArticleAdapter(Protocol):
    """Interface only; installing an adapter is a separate, unimplemented task."""

    def connection_state(self, account_key: str) -> ConnectionState: ...

    def submit(self, *, account_key: str, channel_id: str, idempotency_key: str,
               article: dict[str, Any]) -> SubmissionReceipt: ...


def integration_status(account_key: str, channels: list[dict]) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "account_key": account_key,
        "adapter": {"installed": False, "name": None},
        "session": {"status": "NOT_CONFIGURED", "checked_at": None},
        "capabilities": {"login": False, "draft": False, "publish": False},
        "live_ready": False,
        "channels": [{"project_key": c["project_key"], "name": c["name"],
                      "channel_id": c["channel_id"], "access_verified": False}
                     for c in channels],
        "missing_steps": [
            "Подключить загрузчик статей.",
            "Реализовать вход и безопасное хранение сессии аккаунта.",
            "Проверить права на каждый канал.",
            "Подтвердить сохранение текста и изображений в тестовом черновике.",
        ],
    }


def adapter_contract() -> dict:
    return {
        "version": CONTRACT_VERSION,
        "implemented": False,
        "interface": "product_kb.dzen_integration.ArticleAdapter",
        "connection_states": ["NOT_CONFIGURED", "DISCONNECTED", "EXPIRED", "READY", "ERROR"],
        "receipt_states": ["DRAFT_VERIFIED", "PUBLISHED_VERIFIED", "FAILED", "UNCERTAIN"],
        "requirements": [
            "Resolve account_key and channel_id from server configuration.",
            "Verify session and channel access before submission.",
            "Keep credentials outside API responses, article payloads and logs.",
            "Deduplicate by account_key, channel_id and idempotency_key.",
            "Verify saved title, ordered blocks and all images before reporting success.",
            "Use UNCERTAIN after ambiguous remote outcomes; do not retry automatically.",
            "Never treat an HTTP response or button click alone as verified publication.",
        ],
        "runtime_note": "The queue has no adapter installation or activation endpoint.",
    }
