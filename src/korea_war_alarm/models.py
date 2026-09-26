from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class Level(StrEnum):
    INFO = "INFO"
    WATCH = "WATCH"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return list(Level).index(self)


class Category(StrEnum):
    MISSILE_LAUNCH = "MISSILE_LAUNCH"
    ARTILLERY_ATTACK = "ARTILLERY_ATTACK"
    AIR_ATTACK = "AIR_ATTACK"
    NAVAL_ATTACK = "NAVAL_ATTACK"
    EXPLOSION = "EXPLOSION"
    MILITARY_MOVEMENT = "MILITARY_MOVEMENT"
    AIRSPACE_ANOMALY = "AIRSPACE_ANOMALY"
    MARITIME_ANOMALY = "MARITIME_ANOMALY"
    GNSS_INTERFERENCE = "GNSS_INTERFERENCE"
    SEISMIC_EVENT = "SEISMIC_EVENT"
    INFRASOUND_EVENT = "INFRASOUND_EVENT"
    EVACUATION_REPORT = "EVACUATION_REPORT"
    BORDER_INCIDENT = "BORDER_INCIDENT"
    CYBER_DISRUPTION = "CYBER_DISRUPTION"
    COMMUNICATION_OUTAGE = "COMMUNICATION_OUTAGE"
    CONFLICT_REPORT = "CONFLICT_REPORT"
    UNKNOWN = "UNKNOWN"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: "evt_" + uuid4().hex)
    source_id: str
    evidence_family: str
    source_type: str
    publisher: str
    origin_claim: str = "unknown"
    category: Category = Category.UNKNOWN
    title: str
    body: str = ""
    location: str = "unknown"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    published_at: datetime | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    received_at: datetime = Field(default_factory=utcnow)
    signal_type: str = "NEWS"
    event_time: datetime | None = None
    event_time_basis: Literal["unknown", "source_reported", "simulated"] = "unknown"
    source_publish_time: datetime | None = None
    source_observed_time: datetime | None = None
    kwa_ingested_time: datetime | None = None
    kwa_correlated_time: datetime | None = None
    source_reliability: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0, ge=0, le=1)
    raw_reference: str
    fingerprint: str = ""
    metadata: dict = Field(default_factory=dict)

    @field_validator(
        "published_at",
        "observed_at",
        "received_at",
        "event_time",
        "source_publish_time",
        "source_observed_time",
        "kwa_ingested_time",
        "kwa_correlated_time",
    )
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("timezone required")
            return value.astimezone(UTC)
        return value


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: "inc_" + uuid4().hex)
    category: Category
    location: str
    level: Level = Level.INFO
    confidence: float = 0
    active: bool = True
    first_detected_at: datetime
    updated_at: datetime
    events: list[Event] = Field(default_factory=list)
    evidence_families: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class Alert(BaseModel):
    level: Level = Level.INFO
    active: bool = False
    seq: int = 0
    incident_id: str | None = None
    category: Category | None = None
    confidence: float = 0
    first_detected_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    alert_created_time: datetime | None = None
    evidence_count: int = 0
    independent_family_count: int = 0
    latency_seconds: dict[str, float | None] = Field(default_factory=dict)


class SourceHealth(BaseModel):
    source_id: str
    healthy: bool = False
    enabled: bool = True
    last_success: datetime | None = None
    checked_at: datetime = Field(default_factory=utcnow)
    error: str | None = None
    failures: int = 0
    latency_seconds: float | None = None
    poll_seconds: float = 120
    rejected_entries: int = 0
    health: str = "OFFLINE"
    signal_type: str = "NEWS"
    evidence_family: str = "unresolved"
    last_event: datetime | None = None
    last_http_status: int | None = None
    response_latency_seconds: float | None = None
    parser_failures: int = 0
    rate_limit_until: datetime | None = None
    last_content_change: datetime | None = None
    stale_after_seconds: float | None = None
    observation_age_seconds: float | None = None
    accepted_events: int = 0
    reconnects: int = 0

    def evaluated(self, now: datetime | None = None):
        value = self.model_copy()
        now = now or utcnow()
        if not value.enabled or not value.last_success:
            value.health, value.healthy = "OFFLINE", False
        elif (now - value.last_success).total_seconds() > max(30, value.poll_seconds * 3):
            value.health, value.healthy = "OFFLINE", False
        elif (
            value.stale_after_seconds
            and value.last_content_change
            and (now - value.last_content_change).total_seconds() > value.stale_after_seconds
        ):
            value.health, value.healthy = "STALE", False
        elif not value.healthy or value.rejected_entries:
            value.health, value.healthy = "DEGRADED", False
        else:
            value.health = "HEALTHY"
        return value


class Status(BaseModel):
    service: str = "korea-war-alarm"
    status: str
    mode: str
    alert_level: Level
    active_incident_count: int
    healthy_collectors: int
    total_collectors: int
    updated_at: datetime
    coverage: str = "monitoring_only"
    critical_capable: bool = False
    critical_available: bool = False
    active_source_families: int = 0
    available_signal_types: list[str] = Field(default_factory=list)
    capability_blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    deliveries: dict[str, int] = Field(default_factory=dict)


class SimpleAlert(BaseModel):
    level: int
    active: int
    seq: int
