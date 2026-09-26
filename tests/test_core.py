from datetime import timedelta

import pytest

from korea_war_alarm.config import Config, Source
from korea_war_alarm.core import Core
from korea_war_alarm.models import Category, Level
from korea_war_alarm.normalization import classify
from korea_war_alarm.storage import Store


def test_independent_attack_sensor_critical_and_dedup(event_factory):
    store = Store(":memory:")
    core = Core(store, Config())
    first = event_factory()
    core.ingest(first)
    assert store.alert().level == Level.WATCH
    core.ingest(event_factory(1))
    assert store.alert().level == Level.HIGH
    core.ingest(event_factory(2, source_type="sensor", category=Category.SEISMIC_EVENT))
    assert store.alert().level == Level.CRITICAL
    seq = store.alert().seq
    for _ in range(100):
        assert core.ingest(first) is None
    assert store.alert().seq == seq
    assert len(store.incidents()) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"source_type": "osint"},
        {"origin_claim": "kr_government"},
        {"evidence_family": "same-wire"},
        {"origin_claim": "unknown"},
        {"title": "Identical Korean artillery attack at Seoul"},
        {"publisher": "Same Publisher"},
    ],
)
def test_no_false_critical_from_copies_or_osint(event_factory, override):
    store = Store(":memory:")
    core = Core(store, Config())
    for index in range(20):
        core.ingest(event_factory(index, **override))
    assert store.alert().level.rank <= Level.WARNING.rank


def test_stale_future_and_irrelevant(event_factory):
    store = Store(":memory:")
    core = Core(store, Config())
    base = event_factory()
    for index in range(3):
        core.ingest(event_factory(index, published_at=base.received_at - timedelta(hours=1)))
    assert store.alert().level == Level.INFO
    future = event_factory(9, published_at=base.received_at + timedelta(days=1))
    core.ingest(future)
    assert store.alert().level == Level.INFO
    assert (
        core.ingest(
            event_factory(
                10, title="Attack in Europe", body="", latitude=50, longitude=15, location="europe"
            )
        )
        is None
    )


def test_geography_category_expiry_and_restart(event_factory, tmp_path):
    path = str(tmp_path / "state.sqlite")
    store = Store(path)
    core = Core(store, Config(incident_ttl_seconds=60))
    core.ingest(event_factory())
    core.ingest(event_factory(1, latitude=42, longitude=130, location="north"))
    core.ingest(event_factory(2, category=Category.GNSS_INTERFERENCE))
    assert len(store.incidents()) == 3
    seq = store.alert().seq
    core.tick(event_factory().received_at + timedelta(hours=2))
    assert not store.alert().active
    assert store.alert().seq > seq
    last = store.alert().seq
    store.close()
    reopened = Store(path)
    assert reopened.alert().seq == last


def test_cooldown_new_family_and_contradiction(event_factory):
    store = Store(":memory:")
    core = Core(store, Config())
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    original = store.state("local_notification")["seq"]
    core.ingest(event_factory(2, evidence_family="publisher-1"))
    assert store.state("local_notification")["seq"] == original
    core.ingest(event_factory(3))
    assert store.state("local_notification")["seq"] > original
    core.ingest(event_factory(4, metadata={"contradiction": True}))
    assert store.alert().level == Level.WATCH


def test_korean_government_rejected():
    with pytest.raises(ValueError):
        Source(
            id="bad",
            publisher="bad",
            url="https://example.go.kr/feed",
            operator_country="KR",
            government=True,
        )


@pytest.mark.parametrize(
    "title",
    [
        "Korea military exercise simulates artillery attack",
        "Korea may launch missile",
        "Korea denies air attack",
    ],
)
def test_non_incident_headlines(title):
    assert classify(title) == Category.UNKNOWN
