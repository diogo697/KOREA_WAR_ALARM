import io
import json
from email.utils import format_datetime
from html import escape

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from korea_war_alarm.api import create_app
from korea_war_alarm.cli import main
from korea_war_alarm.collectors import PollCollector
from korea_war_alarm.config import Config, load_config
from korea_war_alarm.core import Core
from korea_war_alarm.deployment import validate_bind
from korea_war_alarm.models import Category, Level, SourceHealth, utcnow
from korea_war_alarm.normalization import classify
from korea_war_alarm.storage import Store


def rss_event(source, title, now):
    document = f"""<rss version="2.0"><channel><title>Test</title><item>
    <title>{escape(title)}</title><link>https://example.org/{source.id}</link>
    <pubDate>{format_datetime(now)}</pubDate></item></channel></rss>"""
    return PollCollector(source, None, None, None).parse(document.encode())[0]


def test_foreign_attack_commentary_cannot_emit_alarm():
    config = load_config("config.example.yaml")
    store = Store(":memory:")
    core = Core(store, config)
    now = utcnow()
    for source, title in zip(
        config.sources,
        [
            "Reuters: Seoul condemns artillery attack on Gaza",
            "Associated Press: Seoul protests artillery fire in Gaza",
        ],
    ):
        assert core.ingest(rss_event(source, title, now)) is None
    assert store.alert().level == Level.INFO
    assert not store.incidents()
    assert store.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 0
    store.close()


def test_real_parsers_correlate_city_attack_with_nearby_sensor():
    config = load_config("config.example.yaml")
    store = Store(":memory:")
    core = Core(store, config)
    now = utcnow()
    for source, title in zip(
        config.sources,
        [
            "Reuters: Seoul under artillery attack, officials warn residents to shelter",
            "Associated Press: Artillery fire reported at Seoul",
        ],
    ):
        core.ingest(rss_event(source, title, now))
    data = {
        "features": [
            {
                "properties": {
                    "place": "Seoul",
                    "net": "us",
                    "time": now.timestamp() * 1000,
                    "mag": 3,
                    "url": "https://example.org/sensor",
                },
                "geometry": {"coordinates": [126.98, 37.57, 1]},
            }
        ]
    }
    sensor = PollCollector(config.sources[3], None, None, None).parse(json.dumps(data).encode())[0]
    core.ingest(sensor)
    incidents = store.incidents()
    assert len(incidents) == 1
    assert len(incidents[0].events) == 3
    assert "corroboration=True" in incidents[0].reasons
    assert incidents[0].level == Level.HIGH
    # 같은 나라지만 먼 센서는 병합하지 않는다.
    sensor = sensor.model_copy(
        update={
            "id": "distant",
            "raw_reference": "https://example.org/far",
            "latitude": 42.0,
            "longitude": 130.0,
        }
    )
    core.ingest(sensor)
    assert len(store.incidents()) == 2
    store.close()


@pytest.mark.parametrize(
    "title",
    [
        "Seoul under artillery attack, officials warn residents to shelter",
        "Seoul hit by shelling in May",
        "May artillery attack on Seoul triggers evacuation",
    ],
)
def test_attack_not_dropped_by_warning_or_month(title):
    assert classify(title) == Category.ARTILLERY_ATTACK


@pytest.mark.parametrize(
    "title",
    [
        "Korea may launch missile",
        "Korea warns of artillery attack",
        "Korea denies air attack",
        "Korea military exercise simulates artillery attack",
    ],
)
def test_speculation_still_excluded(title):
    assert classify(title) == Category.UNKNOWN


def test_capability_separate_from_collector_readiness(tmp_path):
    config = load_config("config.example.yaml")
    config.database = str(tmp_path / "state.sqlite")
    assert not config.critical_capable()
    store = Store(config.database)
    Core(store, config).tick()
    for source in config.sources:
        store.health(SourceHealth(source_id=source.id, healthy=True, last_success=utcnow()))
    store.close()
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        value = client.get("/api/v1/status").json()
        assert value["critical_capable"] is False
        assert any("CRITICAL" in warning for warning in value["warnings"])
        assert client.get("/api/v1/ready").status_code == 200


def test_host_and_origin_rebinding_rejected(tmp_path):
    config = Config(database=str(tmp_path / "state.sqlite"))
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/status", headers={"Host": "attacker.invalid"}).status_code == 400
        for authority in [":secret@127.0.0.1", "127.0.0.1:bad", "127.0.0.1:99999"]:
            assert client.get("/api/v1/status", headers={"Host": authority}).status_code == 400
        assert client.get("/api/v1/status", headers={"Host": "[::1]:8080"}).status_code == 200
        for headers in [
            {"Host": "attacker.invalid", "Origin": "http://attacker.invalid"},
            {"Origin": "http://attacker.invalid"},
        ]:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("ws://127.0.0.1/api/v1/ws", headers=headers):
                    pytest.fail("untrusted origin accepted")
        with client.websocket_connect(
            "ws://127.0.0.1/api/v1/ws", headers={"Origin": "http://127.0.0.1"}
        ):
            pass


def test_external_requires_proxy_https_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("KWA_API_TOKEN", "test-only")
    with pytest.raises(ValueError):
        validate_bind(Config(), "0.0.0.0")
    config = Config(database=str(tmp_path / "state.sqlite"), allowed_hosts=["alarm.example"])
    with TestClient(create_app(config), base_url="https://alarm.example") as client:
        assert client.get("/api/v1/status").status_code == 401
        assert (
            client.get("/api/v1/status", headers={"Authorization": "Bearer test-only"}).status_code
            == 200
        )
        assert client.get("http://alarm.example/api/v1/status").status_code == 403
    monkeypatch.delenv("KWA_API_TOKEN")
    with pytest.raises(ValueError):
        create_app(config)


def test_cli_does_not_send_token_over_external_http(monkeypatch):
    monkeypatch.setenv("KWA_API_TOKEN", "test-only")

    def forbidden_client(**kwargs):
        pytest.fail("HTTP client must not be constructed")

    monkeypatch.setattr(httpx, "Client", forbidden_client)
    assert main(["status", "--url", "http://alarm.example", "--json"]) == 10


def test_cli_json_safe_on_legacy_windows_encoding(monkeypatch):
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1252")
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"warnings": ["현재 소스 구성 제한"]},
            request=httpx.Request("GET", "http://127.0.0.1/api/v1/status"),
        ),
    )
    assert main(["status", "--json"]) == 0
    stream.flush()
    assert json.loads(output.getvalue())["warnings"] == ["현재 소스 구성 제한"]
