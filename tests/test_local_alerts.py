import json

from korea_war_alarm.alerts import local_notify
from korea_war_alarm.config import Config
from korea_war_alarm.core import Core
from korea_war_alarm.models import Category
from korea_war_alarm.storage import Store


async def test_channel_failure_does_not_skip_siren_or_incident_json(
    tmp_path, event_factory, monkeypatch
):
    config = Config(database=str(tmp_path / "db.sqlite"))
    store = Store(config.database)
    core = Core(store, config)
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    core.ingest(event_factory(2, source_type="sensor", category=Category.SEISMIC_EVENT))
    calls = []

    def desktop(payload):
        calls.append("desktop")
        raise RuntimeError("mock desktop outage")

    monkeypatch.setattr("korea_war_alarm.alerts.desktop_notify", desktop)
    monkeypatch.setattr("korea_war_alarm.alerts.siren", lambda: calls.append("siren"))
    payload = store.state("local_notification")
    await local_notify(payload, config, store)
    assert set(calls) == {"desktop", "siren"}
    path = next((tmp_path / "alerts").glob("*.json"))
    assert json.loads(path.read_text("utf-8"))["level"] == "CRITICAL"
    assert store.db.execute("SELECT COUNT(*) FROM deliveries WHERE target=-1").fetchone()[0] == 2
