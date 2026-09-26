from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Level


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    publisher: str
    url: str
    kind: str = "rss"
    source_type: str = "news"
    operator_country: str
    government: bool = False
    enabled: bool = False
    terms_reviewed: bool = False
    reliability: float = Field(default=0.7, ge=0, le=1)
    poll_seconds: float = Field(default=120, ge=5)
    min_poll_seconds: float = Field(default=60, ge=5)
    signal_type: Literal[
        "NEWS",
        "FOREIGN_ALERT",
        "SEISMIC",
        "INFRASOUND",
        "AVIATION",
        "MARITIME",
        "GNSS",
        "SATELLITE",
        "OSINT",
        "NETWORK",
        "OTHER_PHYSICAL",
    ] = "NEWS"
    evidence_family: str = "unresolved"
    stale_after_seconds: float | None = Field(default=None, ge=30)
    license_url: str | None = None

    @model_validator(mode="after")
    def permitted(self):
        if "signal_type" not in self.model_fields_set:
            self.signal_type = (
                "SEISMIC"
                if self.kind in {"usgs", "emsc_ws"}
                else "AVIATION"
                if self.kind == "adsb"
                else "OSINT"
                if self.source_type == "osint"
                else "NEWS"
            )
        if "evidence_family" not in self.model_fields_set and self.kind in {"usgs", "emsc_ws"}:
            self.evidence_family = "usgs"
        host = urlparse(self.url).hostname or ""
        scheme = "wss" if self.kind == "emsc_ws" else "https"
        if urlparse(self.url).scheme != scheme or not host or urlparse(self.url).username:
            raise ValueError("sources require HTTPS or WSS without credentials")
        if self.poll_seconds < self.min_poll_seconds:
            raise ValueError("poll interval violates source minimum")
        if (self.operator_country.upper() == "KR" and self.government) or host.endswith(
            (".go.kr", ".mil.kr")
        ):
            raise ValueError("Korean government sources are excluded")
        if self.kind not in {"rss", "usgs", "emsc_ws", "adsb"}:
            raise ValueError("unsupported collector kind")
        if (
            self.kind == "emsc_ws"
            and self.url != "wss://www.seismicportal.eu/standing_order/websocket"
        ):
            raise ValueError("EMSC adapter requires reviewed endpoint")
        if self.kind == "adsb" and not self.url.startswith("https://opendata.adsb.fi/api/v3/lat/"):
            raise ValueError("ADS-B adapter requires reviewed public endpoint")
        if self.enabled and not self.terms_reviewed:
            raise ValueError("enabled sources require terms_reviewed")
        return self


class Webhook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    min_level: Level = Level.HIGH
    secret_env: str = "KWA_WEBHOOK_SECRET"

    @model_validator(mode="after")
    def permitted(self):
        parts = urlparse(self.url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
            raise ValueError("webhook requires HTTP(S), no URL credentials")
        if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("non-loopback webhook requires HTTPS")
        return self


class MQTT(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    host: str = "localhost"
    port: int = Field(default=8883, ge=1, le=65535)
    tls: bool = True
    username_env: str = "KWA_MQTT_USERNAME"
    password_env: str = "KWA_MQTT_PASSWORD"
    topic_prefix: str = "korea-war-alarm"

    @model_validator(mode="after")
    def valid(self):
        if not self.tls and self.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("non-loopback MQTT requires TLS")
        if not self.topic_prefix or any(x in self.topic_prefix for x in ("#", "+", "\x00")):
            raise ValueError("invalid MQTT topic prefix")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = "data/kwa.sqlite"
    retention_days: int = Field(default=30, ge=1)
    incident_ttl_seconds: int = Field(default=1800, ge=60)
    correlation_seconds: int = Field(default=180, ge=1)
    cooldown_seconds: int = Field(default=300, ge=1)
    threshold: Level = Level.HIGH
    desktop: bool = True
    sound: bool = True
    sources: list[Source] = Field(default_factory=list)
    webhooks: list[Webhook] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost", "::1"])
    api_token_env: str = "KWA_API_TOKEN"
    rate_limit_per_minute: int = Field(default=0, ge=0)
    mqtt: MQTT = Field(default_factory=MQTT)
    log_max_bytes: int = Field(default=5_000_000, ge=10000)

    @model_validator(mode="after")
    def unique_sources(self):
        for host in self.allowed_hosts:
            if not host or any(c in host for c in "/*@?# "):
                raise ValueError("allowed_hosts requires exact hostnames without wildcards")
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source id")
        return self

    def critical_capable(self, available_ids: set[str] | None = None) -> bool:
        # 필요조건만 점검하며 실제 독립 증거 확보나 탐지 성능을 보장하지 않는다.
        enabled = [
            s
            for s in self.sources
            if s.enabled and (available_ids is None or s.id in available_ids)
        ]
        trusted = {
            s.publisher.casefold().strip()
            for s in enabled
            if s.source_type in {"news", "foreign_alert"} and s.reliability >= 0.8
        }
        return (
            len(trusted) >= 2
            and len({s.publisher.casefold().strip() for s in enabled}) >= 3
            and any(
                s.source_type == "foreign_alert"
                or (s.source_type == "sensor" and s.signal_type in {"SEISMIC", "INFRASOUND"})
                for s in enabled
            )
        )


def load_config(path: str | None) -> Config:
    config = (
        Config.model_validate(yaml.safe_load(Path(path).read_text("utf-8")) or {})
        if path
        else Config()
    )
    if path and config.database != ":memory:" and not Path(config.database).is_absolute():
        config.database = str((Path(path).resolve().parent / config.database).resolve())
    return config
