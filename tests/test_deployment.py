import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from korea_war_alarm.alerts import deliver_pending
from korea_war_alarm.api import create_app
from korea_war_alarm.config import Config, Source, Webhook, load_config
from korea_war_alarm.core import Core
from korea_war_alarm.deployment import backup, doctor, initialize, validate_bind
from korea_war_alarm.models import Category
from korea_war_alarm.mqtt import mqtt_payload
from korea_war_alarm.storage import Store


def test_keyless_defaults_and_stable_paths(tmp_path, monkeypatch):
    path = initialize(str(tmp_path))
    with pytest.raises(FileExistsError):
        initialize(str(tmp_path))
    config = load_config(str(path))
    monkeypatch.chdir(tmp_path.parent)
    assert load_config(str(path)).database == config.database
    assert Path(config.database) == tmp_path / "data" / "kwa.sqlite"
    assert len(config.sources) == 6 and all(s.enabled for s in config.sources)
    assert not any("token" in name or "secret" in name for name in Source.model_fields)
    config.desktop = False
    assert doctor(config)["operational_ready"]


def test_readonly_backup_and_schema_migration(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE deliveries(id TEXT PRIMARY KEY,target INTEGER,payload TEXT,attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,status TEXT DEFAULT 'pending')"
        )
    store = Store(str(path))
    with store.db:
        store.set_state("test", 42)
    assert {r[1] for r in store.db.execute("PRAGMA table_info(deliveries)")} >= {
        "destination",
        "context",
    }
    reader = Store(str(path), read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        reader.set_state("test", 0)
    backup(Config(database=str(path)), str(tmp_path / "backup.sqlite"))
    assert Store(str(tmp_path / "backup.sqlite")).state("test") == 42
    with pytest.raises(FileExistsError):
        backup(Config(database=str(path)), str(tmp_path / "backup.sqlite"))
    reader.close()
    store.close()


async def test_webhook_destination_survives_config_reordering(tmp_path, event_factory, monkeypatch):
    monkeypatch.setenv("KWA_WEBHOOK_SECRET", "test-only")
    config = Config(
        database=str(tmp_path / "db.sqlite"), webhooks=[Webhook(url="https://first.example/hook")]
    )
    store = Store(config.database)
    core = Core(store, config)
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    config.webhooks = [Webhook(url="https://second.example/hook")]
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200)
        )
    ) as client:
        await deliver_pending(store, config, client)
    assert requests[0].url.host == "first.example"


def test_ws_critical_and_auth(tmp_path, event_factory, monkeypatch):
    config = Config(database=str(tmp_path / "db.sqlite"))
    store = Store(config.database)
    core = Core(store, config)
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    core.ingest(event_factory(2, category=Category.SEISMIC_EVENT, source_type="sensor"))
    expected = store.stream()
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        with client.websocket_connect("ws://127.0.0.1/api/v1/ws") as socket:
            assert [socket.receive_json() for _ in expected] == expected
        assert client.get("/api/v1/ready").status_code == 503
        monkeypatch.setenv("KWA_API_TOKEN", "fixture-only")
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://127.0.0.1/api/v1/ws"):
                pass


def test_mqtt_payload_includes_freshness(event_factory):
    store = Store(":memory:")
    core = Core(store, Config())
    core.ingest(event_factory())
    payload = mqtt_payload(store.alert(), "2026-01-01T00:00:00Z")
    assert set(payload) == {"level", "active", "seq", "updated_at", "heartbeat"}
    assert json.loads(json.dumps(payload))["level"] == 1


def test_public_bind_requires_local_security_token(monkeypatch):
    monkeypatch.delenv("KWA_API_TOKEN", raising=False)
    validate_bind(Config(), "127.0.0.1")
    with pytest.raises(ValueError):
        validate_bind(Config(), "0.0.0.0")
