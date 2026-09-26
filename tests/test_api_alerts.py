import hashlib
import hmac
import json

import httpx
from fastapi.testclient import TestClient

from korea_war_alarm.alerts import deliver_pending
from korea_war_alarm.api import create_app, encode_sse
from korea_war_alarm.cli import main
from korea_war_alarm.config import Config, Webhook
from korea_war_alarm.core import Core
from korea_war_alarm.models import Category
from korea_war_alarm.storage import Store


def test_rest_contract_and_core_survives_api_shutdown(tmp_path, event_factory):
    config = Config(database=str(tmp_path / "state.sqlite"))
    store = Store(config.database)
    core = Core(store, config)
    core.ingest(event_factory())
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/api/v1/alert/simple").json() == {"level": 1, "active": 1, "seq": 1}
        assert client.get("/api/v1/status").json()["status"] == "stale"
        assert client.get("/api/v1/incidents?min_level=HIGH").json() == []
        assert client.get("/api/v1/incidents/nope").status_code == 404
        assert client.get("/api/v1/incidents?limit=0").status_code == 422
        assert client.get("/openapi.json").json()["openapi"].startswith("3.")
    core.ingest(event_factory(1))
    assert store.alert().level.value == "HIGH"
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/alert/simple").json()["level"] == 3
        assert client.post("/api/v1/alert", json={"level": "CRITICAL"}).status_code == 405


def test_auth_and_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("KWA_API_TOKEN", "test-only-placeholder")
    config = Config(database=str(tmp_path / "state.sqlite"), rate_limit_per_minute=1)
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/sources").status_code == 401
        headers = {"Authorization": "Bearer test-only-placeholder"}
        assert client.get("/api/v1/sources", headers=headers).status_code == 200
        assert client.get("/api/v1/sources", headers=headers).status_code == 429


async def test_webhook_retry_signature_and_critical(tmp_path, event_factory, monkeypatch):
    monkeypatch.setenv("KWA_WEBHOOK_SECRET", "fixture-only")
    config = Config(
        database=str(tmp_path / "state.sqlite"), webhooks=[Webhook(url="https://example.org/hook")]
    )
    store = Store(config.database)
    core = Core(store, config)
    for index in range(3):
        core.ingest(
            event_factory(
                index,
                **(
                    {"source_type": "sensor", "category": Category.SEISMIC_EVENT}
                    if index == 2
                    else {}
                ),
            )
        )
    calls = []

    def handler(request):
        calls.append(request)
        expected = (
            "sha256=" + hmac.new(b"fixture-only", request.content, hashlib.sha256).hexdigest()
        )
        assert request.headers["X-KWA-Signature"] == expected
        return httpx.Response(503 if len(calls) == 1 else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await deliver_pending(store, config, client)
        with store.db:
            store.db.execute("UPDATE deliveries SET next_attempt=0")
        await deliver_pending(store, config, client)
    assert calls[0].headers["Idempotency-Key"] == calls[-1].headers["Idempotency-Key"]
    assert any(json.loads(c.content)["level"] == "CRITICAL" for c in calls)
    assert (
        store.db.execute("SELECT COUNT(*) FROM deliveries WHERE status='delivered'").fetchone()[0]
        == 2
    )


def test_stream_replay_order_and_cursor(event_factory):
    store = Store(":memory:")
    core = Core(store, Config())
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    events = store.stream()
    ids = [e["id"] for e in events]
    assert ids == sorted(set(ids))
    assert store.stream(ids[1]) == events[2:]
    assert "event: alert.changed\n" in encode_sse(events[-1])
    assert "data: " in encode_sse(events[-1])


def test_cli_json_contract(monkeypatch, capsys):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, route):
            return httpx.Response(
                200,
                json={"level": "CRITICAL", "seq": 7},
                request=httpx.Request("GET", "https://example.org"),
            )

    monkeypatch.setattr(httpx, "Client", Client)
    assert main(["alert", "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["seq"] == 7
