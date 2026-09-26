"""출처 시각과 로컬 처리 시각을 구분한다. 미측정 구간은 null로 남긴다."""

from .models import Event


def event_clock(event: Event):
    if event.event_time and event.event_time_basis in {"source_reported", "simulated"}:
        return event.event_time
    return event.published_at


def elapsed(end, start):
    if end is None or start is None or end < start:
        return None
    return (end - start).total_seconds()


def latency(event: Event, alert_created_time=None):
    origin = event.event_time if event.event_time_basis == "source_reported" else None
    return {
        "source_publication": elapsed(event.source_publish_time, origin),
        "observation_age": elapsed(event.source_observed_time, origin),
        "ingestion": elapsed(event.kwa_ingested_time, event.source_observed_time),
        "correlation": elapsed(event.kwa_correlated_time, event.kwa_ingested_time),
        "decision": elapsed(alert_created_time, event.kwa_ingested_time),
        "delivery": None,
        "end_to_end": None,
    }
