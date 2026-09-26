import json
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from .config import Config
from .models import Alert, Category, Event, Incident, Level, utcnow
from .normalization import ATTACKS, PHYSICAL, normalize
from .storage import Store
from .telemetry import event_clock, latency


def correlated(incident: Incident, event: Event, window: int) -> bool:
    if not incident.active:
        return False
    for previous in incident.events:
        previous_time, current_time = event_clock(previous), event_clock(event)
        if previous_time is None or current_time is None:
            continue
        if abs((current_time - previous_time).total_seconds()) > window:
            continue
        compatible = previous.category == event.category or (
            previous.category in ATTACKS | PHYSICAL and event.category in ATTACKS | PHYSICAL
        )
        if not compatible:
            continue
        if all(
            v is not None
            for v in (event.latitude, event.longitude, previous.latitude, previous.longitude)
        ):
            a, b = radians(event.latitude), radians(previous.latitude)
            dlat, dlon = a - b, radians(event.longitude - previous.longitude)
            km = 12742 * asin(
                min(1, sqrt(sin(dlat / 2) ** 2 + cos(a) * cos(b) * sin(dlon / 2) ** 2))
            )
            if km <= 100:
                return True
        elif event.location == previous.location and event.location not in {"unknown", "korea"}:
            return True
    return False


def score(incident: Incident, now: datetime) -> None:
    families: dict[str, Event] = {}
    contents = set()
    publishers = set()
    for event in sorted(incident.events, key=lambda e: (-e.source_reliability, e.id)):
        if (
            event.origin_claim == "kr_government"
            or event.evidence_family == "unresolved"
            or event.metadata.get("clock_invalid")
            or not event.metadata.get("relevant")
            or not event_clock(event)
            or abs((now - event_clock(event)).total_seconds()) > 900
        ):
            continue
        content = event.metadata.get("content_hash")
        publisher = event.publisher.casefold().strip()
        if content in contents or publisher in publishers:
            continue
        contents.add(content)
        publishers.add(publisher)
        old = families.get(event.evidence_family)
        if old is None or event.source_reliability > old.source_reliability:
            families[event.evidence_family] = event
    evidence = list(families.values())
    incident.evidence_families = sorted(families)
    direct = [e for e in evidence if e.category in ATTACKS]
    trustworthy = [
        e
        for e in evidence
        if e.source_reliability >= 0.8 and e.source_type in {"news", "foreign_alert"}
    ]
    corroboration = [
        e for e in evidence if e.category in PHYSICAL or e.source_type == "foreign_alert"
    ]
    contradicted = any(e.metadata.get("contradiction") for e in incident.events)
    confidence = min(
        0.99,
        max((e.source_reliability for e in evidence), default=0) * 0.55
        + max(0, len(evidence) - 1) * 0.12
        + bool(corroboration) * 0.1
        + bool(evidence) * 0.1
        - contradicted * 0.4,
    )
    level = Level.INFO
    if evidence:
        level = Level.WATCH
    elif any(
        e.origin_claim == "unknown"
        and e.metadata.get("relevant")
        and not e.metadata.get("clock_invalid")
        and event_clock(e)
        and abs((now - event_clock(e)).total_seconds()) <= 900
        for e in incident.events
    ):
        # 미확인 공개 보도는 관찰 단계에만 반영하고 독립 증거로 승격하지 않는다.
        level, confidence = Level.WATCH, 0.25
    military = any(
        e.category in ATTACKS | {Category.MISSILE_LAUNCH, Category.CONFLICT_REPORT}
        for e in evidence
    )
    if len(evidence) >= 2 and military and confidence >= 0.5:
        level = Level.WARNING
    if trustworthy and len(evidence) >= 2 and military and confidence >= 0.65:
        level = Level.HIGH
    if (
        direct
        and len(trustworthy) >= 2
        and len(evidence) >= 3
        and corroboration
        and confidence >= 0.85
    ):
        level = Level.CRITICAL
    if contradicted and level.rank > Level.WATCH.rank:
        level = Level.WATCH
    incident.level, incident.confidence = level, round(max(0, confidence), 4)
    incident.reasons = [
        f"independent_families={len(evidence)}",
        f"high_reliability={len(trustworthy)}",
        f"direct_attack={bool(direct)}",
        f"corroboration={bool(corroboration)}",
        f"contradiction={contradicted}",
    ]


class Core:
    def __init__(self, store: Store, config: Config, mode="live"):
        self.store, self.config = store, config
        self.mode = mode
        with store.db:
            store.set_state("mode", mode)

    def ingest(self, raw: Event) -> Incident | None:
        event = normalize(raw)
        if self.mode == "live":
            event.kwa_ingested_time = utcnow()
        with self.store.db:
            if not self.store.add_event(event):
                return None
            if not event.metadata["relevant"] or event.category == Category.UNKNOWN:
                return None
            incidents = self.store.incidents(active=True)
            incident = next(
                (i for i in incidents if correlated(i, event, self.config.correlation_seconds)),
                None,
            )
            created = incident is None
            if self.mode == "live":
                event.kwa_correlated_time = utcnow()
            self.store.db.execute(
                "UPDATE events SET payload=? WHERE id=?", (event.model_dump_json(), event.id)
            )
            if incident is None:
                incident = Incident(
                    category=event.category,
                    location=event.location,
                    first_detected_at=event.received_at,
                    updated_at=event.received_at,
                )
            incident.events.append(event)
            incident.updated_at = event.received_at
            if event.category in ATTACKS:
                incident.category = event.category
            score(incident, event.received_at)
            self.store.save_incident(incident)
            self.store.emit(
                "incident.created" if created else "incident.updated",
                incident.model_dump(mode="json"),
            )
            self._alert(event.received_at, event)
            if self.mode == "live":
                samples = self.store.state("latency_samples", [])
                samples.append(
                    {
                        "source_id": event.source_id,
                        "measured_at": utcnow().isoformat(),
                        "metrics": latency(event),
                    }
                )
                self.store.set_state("latency_samples", samples[-200:])
        return incident

    def _alert(self, now: datetime, trigger: Event | None = None):
        active = self.store.incidents(active=True)
        best = max(active, key=lambda i: (i.level.rank, i.confidence, i.updated_at), default=None)
        old = self.store.alert()
        current = Alert(
            level=best.level if best else Level.INFO,
            active=bool(best),
            incident_id=best.id if best else None,
            category=best.category if best else None,
            confidence=best.confidence if best else 0,
            first_detected_at=best.first_detected_at if best else None,
            updated_at=now,
            evidence_count=len(best.events) if best else 0,
            independent_family_count=len(best.evidence_families) if best else 0,
        )
        changed = old.model_dump(
            exclude={"seq", "updated_at", "alert_created_time", "latency_seconds"}
        ) != current.model_dump(
            exclude={"seq", "updated_at", "alert_created_time", "latency_seconds"}
        )
        signature = [
            current.incident_id,
            current.level.value,
            best.evidence_families if best else [],
        ]
        previous = self.store.state("notified", {})
        eligible = current.level.rank >= self.config.threshold.rank
        # 동일 상태의 주기적 재경보는 생성하지 않는다. 새로운 사건·근거·상승만 재알림한다.
        previous_signature = previous.get("signature", [None, "INFO", []])
        notify = eligible and (
            previous_signature[0] != current.incident_id
            or current.level.rank > Level(previous_signature[1]).rank
            or bool(set(best.evidence_families if best else []) - set(previous_signature[2]))
            or (changed and now.timestamp() - previous.get("at", 0) >= self.config.cooldown_seconds)
        )
        if changed or notify:
            current.alert_created_time = utcnow() if self.mode == "live" else None
            if best and trigger and trigger in best.events and self.mode == "live":
                current.latency_seconds = latency(trigger, current.alert_created_time)
            current.seq = old.seq + 1
            payload = current.model_dump(mode="json")
            payload.update(event="alert.changed", occurred_at=now.isoformat(), notify=notify)
            stream_id = self.store.emit("alert.changed", payload)
            payload["event_id"] = str(stream_id)
            if notify:
                self.store.set_state("notified", {"signature": signature, "at": now.timestamp()})
                for index, hook in enumerate(self.config.webhooks):
                    if current.level.rank >= hook.min_level.rank:
                        self.store.db.execute(
                            "INSERT INTO deliveries(id,target,payload,destination) VALUES (?,?,?,?)",
                            (
                                f"{stream_id}:{index}",
                                index,
                                json.dumps(payload),
                                hook.model_dump_json(),
                            ),
                        )
                self.store.set_state("local_notification", payload)
                self.store.db.execute(
                    "INSERT INTO deliveries(id,target,payload,context) VALUES (?,?,?,?)",
                    (
                        f"{stream_id}:local",
                        -1,
                        json.dumps(payload),
                        best.model_dump_json() if best else None,
                    ),
                )
            self.store.set_state("alert", current.model_dump(mode="json"))

    def tick(self, now: datetime | None = None):
        now = now or utcnow()
        with self.store.db:
            self.store.set_state("heartbeat", now.isoformat())
            for incident in self.store.incidents(active=True):
                if incident.active:
                    old = (incident.level, incident.confidence, incident.active)
                    if now - incident.updated_at > timedelta(
                        seconds=self.config.incident_ttl_seconds
                    ):
                        incident.active = False
                    else:
                        score(incident, now)
                    if old != (incident.level, incident.confidence, incident.active):
                        self.store.save_incident(incident)
                        self.store.emit("incident.updated", incident.model_dump(mode="json"))
            self._alert(now)
