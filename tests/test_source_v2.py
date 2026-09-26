import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from korea_war_alarm.api import create_app
from korea_war_alarm.collectors import PollCollector, WebSocketCollector, make_collector
from korea_war_alarm.config import Config, Source, load_config
from korea_war_alarm.core import Core, correlated
from korea_war_alarm.models import Category, Incident, Level, SourceHealth, utcnow
from korea_war_alarm.source_adapters import parse_adsb, parse_emsc
from korea_war_alarm.storage import Store
from korea_war_alarm.telemetry import latency


def sources():
    return {s.id: s for s in load_config("config.example.yaml").sources}


def message(now, auth="NEIC", action="create"):
    return json.dumps(
        {
            "action": action,
            "data": {
                "properties": {
                    "auth": auth,
                    "lat": 37.56,
                    "lon": 126.98,
                    "time": now.isoformat(),
                    "unid": "fixture-only",
                    "mag": 3.1,
                }
            },
        }
    )


@pytest.mark.parametrize("authority", ["KMA", "KIGAM", "UNKNOWN", "EMSC"])
def test_unreviewed_and_korean_authorities_rejected(authority):
    assert not parse_emsc(message(utcnow(), authority), sources()["emsc-push"], utcnow())


def test_same_upstream_does_not_become_independent(event_factory):
    now = utcnow()
    event = parse_emsc(message(now), sources()["emsc-push"], now)[0]
    store = Store(":memory:")
    core = Core(store, Config())
    core.ingest(event)
    core.ingest(
        event_factory(
            1,
            published_at=now,
            received_at=now,
            evidence_family="usgs",
            publisher="USGS",
            category=Category.SEISMIC_EVENT,
            source_type="sensor",
        )
    )
    assert store.alert().level == Level.WATCH
    assert store.incidents()[0].evidence_families == ["usgs"]
    store.close()


def aircraft(now, **overrides):
    entry = {
        "hex": "fixture",
        "type": "adsb_icao",
        "squawk": "7700",
        "lat": 37.5,
        "lon": 127,
        "seen": 1,
        "seen_pos": 2,
    }
    entry.update(overrides)
    return json.dumps({"now": now.timestamp() * 1000, "ac": [entry]})


@pytest.mark.parametrize("squawk", ["7500", "7600", "7700"])
def test_aviation_signal_never_means_war(squawk):
    now = utcnow()
    event = parse_adsb(aircraft(now, squawk=squawk), sources()["adsb-fi"], now)[0]
    assert event.event_time is None
    assert latency(event)["observation_age"] is None
    store = Store(":memory:")
    core = Core(store, Config())
    core.ingest(event)
    assert store.alert().level == Level.WATCH
    assert store.delivery_counts() == {}
    store.close()


@pytest.mark.parametrize(
    "override",
    [{"squawk": "1200"}, {"type": "tisb_icao"}, {"dbFlags": 1}, {"seen_pos": 90}, {"lat": 10}],
)
def test_non_anomalous_or_stale_aircraft_excluded(override):
    now = utcnow()
    assert not parse_adsb(aircraft(now, **override), sources()["adsb-fi"], now)


def test_stale_aircraft_frame_is_not_healthy():
    now = utcnow()
    with pytest.raises(ValueError):
        parse_adsb(aircraft(now - timedelta(minutes=10)), sources()["adsb-fi"], now)


def test_event_time_correlates_late_confirmation(event_factory):
    now = utcnow()
    sensor = event_factory(
        published_at=now,
        event_time=now,
        event_time_basis="source_reported",
        category=Category.SEISMIC_EVENT,
    )
    news = event_factory(
        1,
        published_at=now + timedelta(minutes=5),
        event_time=now,
        event_time_basis="source_reported",
    )
    incident = Incident(
        category=sensor.category,
        location="seoul",
        first_detected_at=now,
        updated_at=now,
        events=[sensor],
    )
    assert correlated(incident, news, 180)
    news.event_time_basis = "unknown"
    assert not correlated(incident, news, 180)


def test_unknown_latency_and_clock_error_not_fabricated(event_factory):
    event = event_factory()
    assert all(v is None for v in latency(event).values())
    event.event_time = event.received_at - timedelta(seconds=10)
    event.event_time_basis = "source_reported"
    event.source_observed_time = event.received_at
    event.kwa_ingested_time = event.received_at - timedelta(seconds=1)
    assert latency(event)["observation_age"] == 10
    assert latency(event)["ingestion"] is None
    assert latency(event)["source_publication"] is None
    event.event_time_basis = "simulated"
    assert latency(event)["observation_age"] is None


def test_health_silence_staleness_and_offline():
    now = utcnow()
    health = SourceHealth(source_id="quiet", healthy=True, last_success=now)
    assert health.evaluated(now).health == "HEALTHY"
    assert health.last_event is None
    health.stale_after_seconds = 60
    health.last_content_change = now - timedelta(seconds=61)
    assert health.evaluated(now).health == "STALE"
    assert health.evaluated(now + timedelta(hours=1)).health == "OFFLINE"


@pytest.mark.parametrize("failure", ["dns", "500", "json", "429"])
async def test_new_collector_failure_status(failure):
    def handler(request):
        if failure == "dns":
            raise httpx.ConnectError("fixture")
        return httpx.Response(
            500 if failure == "500" else 429 if failure == "429" else 200,
            headers={"Retry-After": "90"},
            content=b"invalid json",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = PollCollector(sources()["adsb-fi"], lambda _: None, lambda _: None, client)
        delay = await collector.once()
        state = await collector.health()
        assert not state.healthy and state.failures == 1
        if failure == "json":
            assert state.parser_failures == 1
        if failure == "429":
            assert delay >= 90 and state.rate_limit_until


async def test_websocket_bad_message_recovery_and_cancellation():
    events, states = [], []
    collector = make_collector(sources()["emsc-push"], events.append, states.append, None)
    assert isinstance(collector, WebSocketCollector)

    class Socket:
        count = 0

        async def recv(self):
            self.count += 1
            if self.count == 1:
                return "broken"
            collector.stopped.set()
            return message(utcnow())

    await collector.session(Socket())
    assert states[0].health == "DEGRADED"
    assert states[-1].health == "HEALTHY"
    assert states[-1].parser_failures == 1 and len(events) == 1


def test_available_capability_requires_healthy_sources(tmp_path):
    config = Config(
        database=str(tmp_path / "state.sqlite"),
        sources=[
            Source(
                id=str(i),
                publisher=str(i),
                url=f"https://example.org/{i}",
                operator_country="US",
                enabled=True,
                terms_reviewed=True,
                source_type="news" if i < 2 else "sensor",
                reliability=0.9,
                signal_type="NEWS" if i < 2 else "SEISMIC",
                evidence_family=str(i),
            )
            for i in range(3)
        ],
    )
    store = Store(config.database)
    Core(store, config).tick()
    for source in config.sources:
        store.health(SourceHealth(source_id=source.id, last_success=utcnow(), healthy=True))
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/status").json()["critical_available"]
        store.health(SourceHealth(source_id="0", last_success=utcnow(), healthy=False, failures=1))
        status = client.get("/api/v1/status").json()
        assert status["critical_capable"] and not status["critical_available"]
        assert "required_sources_or_core_unavailable" in status["capability_blockers"]
        assert client.get("/api/v1/alert/simple").json() == {"level": 0, "active": 0, "seq": 0}
        assert client.get("/api/v1/latency").json()["end_to_end"] is None
    store.close()


def test_source_rate_floor():
    with pytest.raises(ValueError):
        Source(
            id="fast",
            publisher="test",
            url="https://example.org",
            operator_country="US",
            poll_seconds=5,
        )


async def test_quiet_websocket_is_alive_with_pong():
    states = []
    collector = make_collector(sources()["emsc-push"], lambda _: None, states.append, None)
    collector.heartbeat_seconds = 0.001

    class Socket:
        async def recv(self):
            await asyncio.Event().wait()

        async def ping(self):
            collector.stopped.set()
            pong = asyncio.get_running_loop().create_future()
            pong.set_result(None)
            return pong

    await collector.session(Socket())
    assert states[-1].health == "HEALTHY"
    assert states[-1].last_event is None
    assert states[-1].response_latency_seconds is not None


async def test_websocket_reconnect_recovers(monkeypatch):
    import websockets

    events, states = [], []
    collector = make_collector(sources()["emsc-push"], events.append, states.append, None)
    collector.reconnect_seconds = 0.001

    class Connection:
        attempts = 0

        async def __aenter__(self):
            Connection.attempts += 1
            if Connection.attempts == 1:
                raise ConnectionError("fixture")
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            collector.stopped.set()
            return message(utcnow())

    monkeypatch.setattr(websockets, "connect", lambda *args, **kwargs: Connection())
    await collector.start()
    assert Connection.attempts == 2
    assert states[0].health == "OFFLINE" and states[-1].health == "HEALTHY"
    assert collector.state.reconnects == 1 and len(events) == 1
