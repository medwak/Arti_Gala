"""Outbound webhook delivery (HMAC-signed, retried) and inbound signature checks."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import uuid
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import WebhookDelivery, WebhookSubscription
from .events import topic_matches

log = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-ArtiGala-Signature"
EVENT_HEADER = "X-ArtiGala-Event"
DELIVERY_HEADER = "X-ArtiGala-Delivery"


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(secret, body), signature.strip())


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


def validate_target_url(url: str, allow_private: bool) -> None:
    """Reject URLs that are not http(s) or that point into private networks (SSRF guard)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("webhook URL must be an absolute http(s) URL")
    if allow_private:
        return
    host = parts.hostname
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve webhook host {host!r}") from exc
    for info in infos:
        if not _is_public_ip(info[4][0]):
            raise ValueError(f"webhook host {host!r} resolves to a non-public address")


class WebhookDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        timeout: float = 10.0,
        allow_private: bool = False,
        backoff_base: float = 1.0,
        user_agent: str = "ArtiGala-Webhooks/0.1",
    ) -> None:
        self._sessions = session_factory
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout, headers={"User-Agent": user_agent})
        self.max_attempts = max_attempts
        self.allow_private = allow_private
        self.backoff_base = backoff_base

    async def aclose(self) -> None:
        await self._client.aclose()

    def _subscriptions_for(self, event: str) -> list[tuple[int, str, str]]:
        with self._sessions() as db:
            subs = db.scalars(select(WebhookSubscription).where(WebhookSubscription.active.is_(True))).all()
            return [(s.id, s.url, s.secret) for s in subs if topic_matches(event, s.events)]

    def _record(self, **fields) -> None:
        with self._sessions() as db:
            db.add(WebhookDelivery(**fields))
            db.commit()

    async def dispatch(self, message: dict) -> None:
        subs = await asyncio.to_thread(self._subscriptions_for, message["event"])
        if subs:
            await asyncio.gather(*(self.deliver(sub_id, url, secret, message) for sub_id, url, secret in subs))

    async def deliver(self, sub_id: int, url: str, secret: str, message: dict) -> bool:
        delivery_id = uuid.uuid4().hex
        body = json.dumps(message, default=str).encode()
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: message["event"],
            DELIVERY_HEADER: delivery_id,
            SIGNATURE_HEADER: sign(secret, body),
        }
        status_code: int | None = None
        error: str | None = None
        attempts = 0
        success = False
        for attempts in range(1, self.max_attempts + 1):
            try:
                await asyncio.to_thread(validate_target_url, url, self.allow_private)
                response = await self._client.post(url, content=body, headers=headers)
                status_code = response.status_code
                if 200 <= status_code < 300:
                    success, error = True, None
                    break
                error = f"HTTP {status_code}"
                if 400 <= status_code < 500 and status_code not in (408, 429):
                    break  # receiver rejected it; retrying won't help
            except ValueError as exc:
                error = str(exc)
                break
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            if attempts < self.max_attempts:
                await asyncio.sleep(self.backoff_base * 2 ** (attempts - 1))
        await asyncio.to_thread(
            self._record,
            subscription_id=sub_id,
            delivery_id=delivery_id,
            event=message["event"],
            attempts=attempts,
            status_code=status_code,
            success=success,
            error=error,
        )
        if not success:
            log.warning("webhook %s to %s failed: %s", message["event"], url, error)
        return success
