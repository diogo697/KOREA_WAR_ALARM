import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

from .config import Config, Webhook
from .models import Incident
from .storage import Store

log = logging.getLogger(__name__)


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver_pending(store: Store, config: Config, client: httpx.AsyncClient):
    rows = store.db.execute(
        "SELECT * FROM deliveries WHERE target>=0 AND status='pending' AND next_attempt<=? LIMIT 20",
        (time.time(),),
    ).fetchall()
    for row in rows:
        try:
            if not row["destination"]:
                raise ValueError("legacy delivery needs explicit destination migration")
            hook = Webhook.model_validate_json(row["destination"])
            secret = os.environ.get(hook.secret_env)
            if not secret:
                raise ValueError("webhook secret missing")
            body = row["payload"].encode()
            response = await client.post(
                hook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-KWA-Signature": signature(secret, body),
                    "Idempotency-Key": row["id"],
                },
            )
            response.raise_for_status()
            with store.db:
                store.db.execute(
                    "UPDATE deliveries SET status='delivered' WHERE id=?", (row["id"],)
                )
        except Exception as exc:
            attempts = row["attempts"] + 1
            with store.db:
                store.db.execute(
                    "UPDATE deliveries SET attempts=?,next_attempt=?,status=? WHERE id=?",
                    (
                        attempts,
                        time.time() + min(3600, 2**attempts),
                        "failed" if attempts >= 8 else "pending",
                        row["id"],
                    ),
                )
            log.warning(
                json.dumps(
                    {"event": "webhook.failure", "error": type(exc).__name__, "attempt": attempts}
                )
            )


def desktop_notify(payload: dict):
    from plyer import notification

    notification.notify(
        title="Korea War Alarm",
        message=f"{payload['level']}: {payload['category']}",
        app_name="Korea War Alarm",
        timeout=10,
    )


def siren():
    if sys.platform == "win32":
        import winsound

        for hz in (900, 1200, 900, 1200):
            winsound.Beep(hz, 250)
    else:
        print("\a", end="", flush=True)


async def local_notify(payload: dict, config: Config, store: Store, context: str | None = None):
    print(json.dumps(payload), flush=True)
    incident_id = payload.get("incident_id")
    if incident_id:
        incident = Incident.model_validate_json(context) if context else store.incident(incident_id)
        if incident:
            target = Path(config.database).parent / "alerts"
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{incident.id}-{payload['seq']}.json").write_text(
                incident.model_dump_json(indent=2), "utf-8"
            )
    actions = []
    if config.desktop:
        actions.append(asyncio.to_thread(desktop_notify, payload))
    if config.sound and payload["level"] == "CRITICAL":
        actions.append(asyncio.to_thread(siren))
    for result in await asyncio.gather(*actions, return_exceptions=True):
        if isinstance(result, Exception):
            log.warning(
                json.dumps({"event": "local_alert.failure", "error": type(result).__name__})
            )


async def webhook_worker(config: Config):
    # 별도 연결·태스크를 사용해 webhook 지연이 수집을 막지 않게 한다.
    store = Store(config.database)
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            while True:
                await deliver_pending(store, config, client)
                await asyncio.sleep(0.2)
    finally:
        store.close()


async def alert_worker(config: Config):
    store = Store(config.database)
    try:
        while True:
            rows = store.db.execute(
                "SELECT * FROM deliveries WHERE target=-1 AND status='pending' ORDER BY rowid LIMIT 20"
            ).fetchall()
            for row in rows:
                try:
                    await local_notify(json.loads(row["payload"]), config, store, row["context"])
                    status = "delivered"
                except Exception as exc:
                    log.warning(
                        json.dumps({"event": "local_alert.failure", "error": type(exc).__name__})
                    )
                    status = "failed"
                with store.db:
                    store.db.execute(
                        "UPDATE deliveries SET status=? WHERE id=?", (status, row["id"])
                    )
            await asyncio.sleep(0.1)
    finally:
        store.close()
