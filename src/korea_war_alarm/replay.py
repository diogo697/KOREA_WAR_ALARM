import json
from datetime import datetime
from pathlib import Path
from time import perf_counter

from .collectors import PollCollector
from .config import Config, Source
from .core import Core
from .models import Event, Level
from .storage import Store


def replay(path: str) -> dict:
    fixture = json.loads(Path(path).read_text("utf-8"))
    store = Store(":memory:")
    config = Config(desktop=False, sound=False)
    core = Core(store, config, mode="synthetic")
    first = high = critical = None
    transitions = []
    duplicate = 0
    contributions = {}
    processing_ms = []
    latency = {}
    false_positives = 0
    ceiling = fixture.get("max_allowed_level")
    raw_events = list(fixture.get("events", []))
    if "source_records" in fixture:
        sources = {s["id"]: Source.model_validate(s) for s in fixture["sources"]}
        for record in fixture["source_records"]:
            source = sources[record["source_id"]]
            content = record["content"]
            content = content if isinstance(content, str) else json.dumps(content)
            events = PollCollector(source, None, None, None).parse(
                content.encode(), now=datetime.fromisoformat(record["received_at"])
            )
            raw_events.extend(e.model_dump(mode="json") for e in events)
    raw_events.sort(
        key=lambda item: datetime.fromisoformat(item["received_at"].replace("Z", "+00:00"))
    )
    for raw in raw_events:
        event = Event.model_validate(raw)
        contributions.setdefault(event.source_id, event.received_at.isoformat())
        before = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        started = perf_counter()
        result = core.ingest(event)
        processing_ms.append((perf_counter() - started) * 1000)
        duplicate += store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
        if event.published_at and event.received_at >= event.published_at:
            latency.setdefault(event.source_id, []).append(
                (event.received_at - event.published_at).total_seconds()
            )
        if result:
            first = first or event.received_at.isoformat()
        level = store.alert().level
        if not transitions or transitions[-1]["level"] != level.value:
            transitions.append({"time": event.received_at.isoformat(), "level": level.value})
        if ceiling and level.rank > Level(ceiling).rank:
            false_positives += 1
        if level.rank >= Level.HIGH.rank:
            high = high or event.received_at.isoformat()
        if level == Level.CRITICAL:
            critical = critical or event.received_at.isoformat()
    levels = [i.level.value for i in store.incidents()]
    notifications = [
        e
        for e in store.stream(limit=10000)
        if e["event"] == "alert.changed" and e["data"]["notify"]
    ]
    expected = fixture.get("expected_level")
    report = {
        "fixture_kind": fixture.get("kind", "synthetic"),
        "timing_basis": "fixture timestamps; not measured live latency",
        "transitions": transitions,
        "first_detection_time": first,
        "high_alert_time": high,
        "critical_alert_time": critical,
        "duplicate_event_count": duplicate,
        "notification_count": len(notifications),
        "source_contribution": contributions,
        "source_latency_seconds": {
            key: {"min": min(values), "mean": sum(values) / len(values), "max": max(values)}
            for key, values in latency.items()
        },
        "max_core_processing_ms": max(processing_ms, default=0),
        "false_positive_count": false_positives if ceiling else None,
        "final_levels": levels,
        "expected_level": expected,
        "passed": (expected is None or store.alert().level.value == expected)
        and false_positives == 0,
    }
    store.close()
    return report
