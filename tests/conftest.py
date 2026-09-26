from datetime import UTC, datetime, timedelta

import pytest

from korea_war_alarm.models import Category, Event


@pytest.fixture
def event_factory():
    now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)

    def make(index=0, **kwargs):
        values = dict(
            source_id=f"source-{index}",
            publisher=f"Publisher {index}",
            evidence_family=f"publisher-{index}",
            origin_claim="original",
            source_type="news",
            title=f"Korean artillery attack reported at Seoul ({index})",
            location="seoul",
            category=Category.ARTILLERY_ATTACK,
            source_reliability=0.9,
            latitude=37.5,
            longitude=127.0,
            published_at=now,
            received_at=now + timedelta(seconds=index),
            observed_at=now,
            raw_reference=f"https://example.org/{index}",
        )
        values.update(kwargs)
        return Event(**values)

    return make
