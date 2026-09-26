import asyncio
import calendar
import hashlib
import json
import math
from collections import deque
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Protocol

import feedparser
import httpx

from .config import Source
from .models import Category, Event, SourceHealth, utcnow
from .normalization import classify, clean
from .source_adapters import parse_adsb, parse_emsc


class Collector(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> SourceHealth: ...


class PollCollector:
    def __init__(self, source: Source, ingest, publish_health, client: httpx.AsyncClient):
        self.source, self.ingest, self.publish_health, self.client = (
            source,
            ingest,
            publish_health,
            client,
        )
        self.state = SourceHealth(
            source_id=source.id,
            enabled=source.enabled,
            poll_seconds=source.poll_seconds,
            signal_type=source.signal_type,
            evidence_family=source.evidence_family,
            stale_after_seconds=source.stale_after_seconds,
        )
        self.headers = {}
        self.stopped = asyncio.Event()
        self.content_hash = None
        self.seen = deque(maxlen=2000)

    async def health(self) -> SourceHealth:
        return self.state.evaluated()

    def consume(self, events):
        for event in events:
            identity = (event.raw_reference, event.title)
            if identity not in self.seen:
                self.seen.append(identity)
                self.state.last_event = event.received_at
                self.state.accepted_events += 1
            self.ingest(event)
        ages = [
            (e.source_observed_time - e.event_time).total_seconds()
            for e in events
            if e.event_time
            and e.event_time_basis == "source_reported"
            and e.source_observed_time
            and e.source_observed_time >= e.event_time
        ]
        self.state.observation_age_seconds = min(ages) if ages else None

    async def stop(self):
        self.stopped.set()

    async def once(self) -> float:
        delay = self.source.poll_seconds
        self.state.checked_at = utcnow()
        self.state.last_http_status = None
        started = perf_counter()
        try:
            headers = dict(self.headers)
            async with self.client.stream("GET", self.source.url, headers=headers) as response:
                self.state.last_http_status = response.status_code
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 5_000_000:
                        raise ValueError("feed exceeds size limit")
            self.state.response_latency_seconds = perf_counter() - started
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = max(delay, float(retry))
                except ValueError:
                    try:
                        delay = max(
                            delay, (parsedate_to_datetime(retry) - utcnow()).total_seconds()
                        )
                    except (TypeError, ValueError):
                        pass
                if not math.isfinite(delay) or delay < 0:
                    delay = 1800
                self.state.rate_limit_until = utcnow() + timedelta(seconds=delay)
                response.raise_for_status()
            if response.status_code != 304:
                response.raise_for_status()
                try:
                    events = self.parse(bytes(content))
                except (ValueError, TypeError, KeyError):
                    self.state.parser_failures += 1
                    raise
                digest = hashlib.sha256(content).hexdigest()
                if digest != self.content_hash:
                    self.state.last_content_change = utcnow()
                    self.content_hash = digest
                self.consume(events)
                latencies = [
                    (e.received_at - e.published_at).total_seconds()
                    for e in events
                    if e.published_at and e.published_at <= e.received_at
                ]
                self.state.latency_seconds = min(latencies) if latencies else None
                for header, conditional in (
                    ("ETag", "If-None-Match"),
                    ("Last-Modified", "If-Modified-Since"),
                ):
                    if response.headers.get(header):
                        self.headers[conditional] = response.headers[header]
            self.state.healthy, self.state.error, self.state.failures = True, None, 0
            self.state.last_success = utcnow()
            self.state.rate_limit_until = None
        except Exception as exc:
            self.state.response_latency_seconds = perf_counter() - started
            self.state.healthy = False
            # 원문 예외에는 인증 URL 등이 포함될 수 있어 유형만 기록한다.
            self.state.error = type(exc).__name__
            self.state.failures += 1
            delay = max(
                delay, min(1800, self.source.poll_seconds * 2 ** min(self.state.failures, 5))
            )
        self.publish_health(self.state.evaluated())
        return delay

    def parse(self, content: bytes, now: datetime | None = None) -> list[Event]:
        now, events = now or utcnow(), []
        self.state.rejected_entries = 0
        if self.source.kind == "adsb":
            return parse_adsb(content, self.source, now)
        if self.source.kind == "emsc_ws":
            return parse_emsc(content, self.source, now)
        if self.source.kind == "usgs":
            data = json.loads(content)
            for feature in data["features"]:
                try:
                    props = feature["properties"]
                    if props.get("net") != "us":
                        continue
                    lon, lat, *_ = feature["geometry"]["coordinates"]
                    if not (33 <= lat <= 43 and 124 <= lon <= 132):
                        continue
                    events.append(
                        Event(
                            source_id=self.source.id,
                            publisher=self.source.publisher,
                            evidence_family="usgs",
                            origin_claim="original",
                            source_type="sensor",
                            signal_type="SEISMIC",
                            category=Category.SEISMIC_EVENT,
                            title=f"Seismic event: {props['place']}",
                            latitude=lat,
                            longitude=lon,
                            location="korea",
                            published_at=datetime.fromtimestamp(props["time"] / 1000, UTC),
                            event_time=datetime.fromtimestamp(props["time"] / 1000, UTC),
                            event_time_basis="source_reported",
                            source_observed_time=now,
                            observed_at=now,
                            received_at=now,
                            source_reliability=self.source.reliability,
                            raw_reference=props["url"],
                            metadata={"magnitude": props.get("mag")},
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    self.state.rejected_entries += 1
            return events
        data = feedparser.parse(content)
        if data.bozo:
            raise ValueError("malformed RSS")
        if not data.version:
            raise ValueError("not an RSS/Atom feed")
        for entry in data.entries[:1000]:
            title = clean(entry.get("title", ""))
            if not title or not entry.get("link"):
                continue
            timestamp = entry.get("published_parsed") or entry.get("updated_parsed")
            events.append(
                Event(
                    source_id=self.source.id,
                    publisher=self.source.publisher,
                    evidence_family="unresolved",
                    source_type=self.source.source_type,
                    signal_type=self.source.signal_type,
                    title=title,
                    body=clean(entry.get("summary", "")),
                    category=classify(title),
                    published_at=datetime.fromtimestamp(calendar.timegm(timestamp), UTC)
                    if timestamp
                    else None,
                    observed_at=now,
                    received_at=now,
                    source_publish_time=datetime.fromtimestamp(calendar.timegm(timestamp), UTC)
                    if timestamp
                    else None,
                    source_observed_time=now,
                    raw_reference=entry.link,
                    source_reliability=self.source.reliability,
                    metadata={
                        "rss": True,
                        "author": entry.get("author", self.source.publisher),
                        "license_url": self.source.license_url,
                        "changes": "HTML removed; whitespace normalized",
                    },
                )
            )
        return events

    async def start(self):
        while not self.stopped.is_set():
            delay = await self.once()
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=delay)
            except TimeoutError:
                pass


class WebSocketCollector(PollCollector):
    """읽기 전용 EMSC push 수집. 무소식과 연결 장애를 ping/pong으로 구분한다."""

    heartbeat_seconds = 15
    reconnect_seconds = 5

    async def session(self, socket):
        while not self.stopped.is_set():
            try:
                message = await asyncio.wait_for(socket.recv(), timeout=self.heartbeat_seconds)
            except TimeoutError:
                started = perf_counter()
                pong = await socket.ping()
                await asyncio.wait_for(pong, timeout=5)
                self.state.response_latency_seconds = perf_counter() - started
            else:
                try:
                    self.consume(self.parse(message))
                    self.state.last_content_change = utcnow()
                    self.state.rejected_entries = 0
                except (ValueError, TypeError, KeyError):
                    self.state.parser_failures += 1
                    self.state.rejected_entries += 1
            self.state.last_success = self.state.checked_at = utcnow()
            self.state.healthy, self.state.failures, self.state.error = True, 0, None
            self.publish_health(self.state.evaluated())

    async def start(self):
        import websockets

        delay = self.reconnect_seconds
        while not self.stopped.is_set():
            try:
                async with websockets.connect(
                    self.source.url,
                    open_timeout=10,
                    close_timeout=3,
                    max_size=1_000_000,
                    max_queue=16,
                    ping_interval=15,
                    ping_timeout=10,
                ) as socket:
                    self.state.last_success = self.state.checked_at = utcnow()
                    self.state.healthy = True
                    self.publish_health(self.state.evaluated())
                    await self.session(socket)
                    delay = self.reconnect_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.healthy = False
                self.state.error = type(exc).__name__
                self.state.failures += 1
                self.state.reconnects += 1
                self.publish_health(self.state.evaluated())
                try:
                    await asyncio.wait_for(self.stopped.wait(), timeout=delay)
                except TimeoutError:
                    pass
                delay = min(300, delay * 2)


def make_collector(source, ingest, publish_health, client):
    cls = WebSocketCollector if source.kind == "emsc_ws" else PollCollector
    return cls(source, ingest, publish_health, client)
