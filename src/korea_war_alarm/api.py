import asyncio
import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Config
from .models import Alert, Category, Incident, Level, SimpleAlert, SourceHealth, Status, utcnow
from .storage import Store


def encode_sse(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"


def create_app(config: Config) -> FastAPI:
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    trusted_hosts = {host.lower() for host in config.allowed_hosts}
    if trusted_hosts - local_hosts and not os.environ.get(config.api_token_env):
        raise ValueError("external allowed_hosts requires an API token")

    def trusted_authority(authority: str) -> bool:
        try:
            parsed = urlsplit("//" + authority)
            port = parsed.port
            return bool(
                parsed.hostname in trusted_hosts
                and parsed.username is None
                and parsed.password is None
                and (port is None or 1 <= port <= 65535)
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            return False

    bootstrap = Store(config.database)
    bootstrap.close()
    app = FastAPI(title="Korea War Alarm", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Last-Event-ID"],
    )
    requests = defaultdict(deque)

    @contextmanager
    def database():
        store = Store(config.database, read_only=True)
        try:
            yield store
        finally:
            store.close()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not trusted_authority(request.headers.get("host", "")):
            return JSONResponse(
                {"error": {"code": 400, "message": "Invalid host"}}, status_code=400
            )
        if request.url.hostname not in local_hosts and request.url.scheme != "https":
            return JSONResponse(
                {"error": {"code": 403, "message": "HTTPS required"}}, status_code=403
            )
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            token = os.environ.get(config.api_token_env)
            if token and not hmac.compare_digest(
                request.headers.get("Authorization", ""), f"Bearer {token}"
            ):
                return JSONResponse(
                    {"error": {"code": 401, "message": "Unauthorized"}}, status_code=401
                )
            if config.rate_limit_per_minute:
                now = time.monotonic()
                for key in list(requests):
                    if not requests[key] or requests[key][-1] <= now - 60:
                        del requests[key]
                bucket = requests[request.client.host if request.client else "local"]
                while bucket and bucket[0] <= now - 60:
                    bucket.popleft()
                if len(bucket) >= config.rate_limit_per_minute:
                    return JSONResponse(
                        {"error": {"code": 429, "message": "Rate limited"}},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
                bucket.append(now)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            )
        logging.getLogger("kwa.api").info(
            json.dumps(
                {"method": request.method, "path": request.url.path, "status": response.status_code}
            )
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def error_handler(request, exc):
        return JSONResponse(
            {"error": {"code": exc.status_code, "message": str(exc.detail)}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        return JSONResponse(
            {"error": {"code": 422, "message": "Invalid request parameters"}}, status_code=422
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/status", response_model=Status)
    def status():
        with database() as store:
            heartbeat = store.state("heartbeat")
            updated = (
                datetime.fromisoformat(heartbeat)
                if heartbeat
                else datetime.fromtimestamp(0, tz=utcnow().tzinfo)
            )
            sources = [s.evaluated() for s in store.sources()]
            healthy_ids = {
                s.source_id
                for s in sources
                if s.enabled
                and s.healthy
                and s.last_success
                and (utcnow() - s.last_success).total_seconds() < s.poll_seconds * 3
            }
            enabled = [s for s in config.sources if s.enabled]
            ready = bool(enabled) and all(s.id in healthy_ids for s in enabled)
            warnings = (
                [] if ready else ["공개 소스 수집이 시작되지 않았거나 일부 소스에 연결할 수 없음."]
            )
            if any(s.enabled and s.source_id not in healthy_ids for s in sources):
                warnings.append("일부 활성 수집 소스 장애 또는 응답 지연")
            capable = config.critical_capable()
            available = (
                config.critical_capable(healthy_ids) and (utcnow() - updated).total_seconds() < 10
            )
            families = {
                s.evidence_family
                for s in enabled
                if s.id in healthy_ids and s.evidence_family != "unresolved"
            }
            blockers = []
            if not capable:
                blockers.append("configured_evidence_insufficient")
            elif not available:
                blockers.append("required_sources_or_core_unavailable")
            if not capable:
                warnings.append(
                    "현재 소스 구성으로는 CRITICAL·사이렌 조건 충족 불가. 수집 정상과 경보 능력은 별개임."
                )
            elif not available:
                warnings.append("경보 필요 소스 또는 Core가 현재 사용 불가.")
            return Status(
                status="running" if (utcnow() - updated).total_seconds() < 10 else "stale",
                mode=store.state("mode", "live"),
                alert_level=store.alert().level,
                active_incident_count=sum(i.active for i in store.incidents()),
                healthy_collectors=sum(
                    s.enabled
                    and s.healthy
                    and s.last_success is not None
                    and (utcnow() - s.last_success).total_seconds() < s.poll_seconds * 3
                    for s in sources
                ),
                total_collectors=sum(s.enabled for s in sources),
                updated_at=updated,
                coverage="public_feeds" if ready else "degraded",
                critical_capable=capable,
                critical_available=available,
                active_source_families=len(families),
                available_signal_types=sorted(
                    {s.signal_type for s in enabled if s.id in healthy_ids}
                ),
                capability_blockers=blockers,
                warnings=warnings,
                deliveries=store.delivery_counts(),
            )

    @app.get("/api/v1/ready", response_model=Status)
    def ready():
        current = status()
        return JSONResponse(
            current.model_dump(mode="json"),
            status_code=200
            if current.status == "running" and current.coverage == "public_feeds"
            else 503,
        )

    @app.get("/api/v1/alert", response_model=Alert)
    def alert():
        with database() as store:
            return store.alert()

    @app.get("/api/v1/alert/simple", response_model=SimpleAlert)
    def simple():
        value = alert()
        return SimpleAlert(level=value.level.rank, active=int(value.active), seq=value.seq)

    @app.get("/api/v1/incidents", response_model=list[Incident])
    def incidents(
        limit: int = Query(50, ge=1, le=200),
        min_level: Level = Level.INFO,
        category: Category | None = None,
        active: bool | None = None,
    ):
        with database() as store:
            return [
                i
                for i in store.incidents(active=active)
                if i.level.rank >= min_level.rank
                and (category is None or i.category == category)
                and (active is None or i.active == active)
            ][:limit]

    @app.get("/api/v1/incidents/{incident_id}", response_model=Incident)
    def incident(incident_id: str):
        with database() as store:
            value = store.incident(incident_id)
            if value:
                return value
        raise HTTPException(404, "Incident not found")

    @app.get("/api/v1/sources", response_model=list[SourceHealth])
    def sources():
        with database() as store:
            return [value.evaluated() for value in store.sources()]

    @app.get("/api/v1/latency")
    def latency_report():
        with database() as store:
            samples = store.state("latency_samples", [])
        # 관측된 사건 나이는 최초 게시 지연의 실측값이 아니다.
        summaries = {}
        for sample in samples:
            for key, value in sample["metrics"].items():
                if value is not None:
                    summaries.setdefault(sample["source_id"], {}).setdefault(key, []).append(value)
        for metrics in summaries.values():
            for key, values in metrics.items():
                values.sort()
                metrics[key] = {
                    "count": len(values),
                    "p50": values[(len(values) - 1) // 2],
                    "p95": values[min(len(values) - 1, int(len(values) * 0.95))],
                }
        return {
            "sample_count": len(samples),
            "window": "last_200_relevant_events",
            "sources": summaries,
            "delivery": None,
            "end_to_end": None,
        }

    @app.get(
        "/api/v1/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
    )
    async def stream(request: Request, after: int = Query(0, ge=0)):
        try:
            cursor = int(request.headers.get("Last-Event-ID", after))
            if cursor < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Invalid Last-Event-ID") from None

        async def generate():
            nonlocal cursor
            last_heartbeat = time.monotonic()
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                with database() as store:
                    bounds = store.db.execute("SELECT MIN(id),MAX(id) FROM stream").fetchone()
                    if bounds[0] is not None and (
                        cursor > bounds[1] or (cursor and cursor < bounds[0] - 1)
                    ):
                        cursor = bounds[0] - 1
                        yield encode_sse(
                            {
                                "id": cursor,
                                "event": "stream.reset",
                                "data": store.alert().model_dump(mode="json"),
                            }
                        )
                    events = store.stream(cursor)
                for event in events:
                    cursor = event["id"]
                    yield encode_sse(event)
                if time.monotonic() - last_heartbeat >= 5:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.1 if events else 0.25)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    @app.websocket("/api/v1/ws")
    async def websocket(socket: WebSocket):
        token = os.environ.get(config.api_token_env)
        origin = socket.headers.get("origin")
        authority = socket.headers.get("host", "")
        if not trusted_authority(authority):
            await socket.close(code=1008)
            return
        if socket.url.hostname not in local_hosts and socket.url.scheme != "wss":
            await socket.close(code=1008)
            return
        # Host를 허용 목록으로 검증한 뒤에만 동일 출처를 허용한다.
        allowed = config.cors_origins + [f"https://{authority}"]
        if socket.url.hostname in local_hosts:
            allowed.append(f"http://{authority}")
        if (
            token
            and not hmac.compare_digest(socket.headers.get("authorization", ""), f"Bearer {token}")
        ) or (origin and origin not in allowed):
            await socket.close(code=1008)
            return
        try:
            cursor = int(socket.query_params.get("after", "0"))
            if cursor < 0:
                raise ValueError
        except ValueError:
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            while True:
                with database() as store:
                    bounds = store.db.execute("SELECT MIN(id),MAX(id) FROM stream").fetchone()
                    reset = bounds[0] is not None and (
                        cursor > bounds[1] or (cursor and cursor < bounds[0] - 1)
                    )
                    if reset:
                        cursor = bounds[0] - 1
                    events = store.stream(cursor)
                if reset:
                    await asyncio.wait_for(
                        socket.send_json({"event": "stream.reset", "id": cursor, "data": {}}), 5
                    )
                for event in events:
                    await asyncio.wait_for(socket.send_json(event), 5)
                    cursor = event["id"]
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=0.25)
                    if message["type"] == "websocket.disconnect":
                        return
                    # 서버 발신 전용이며 command는 처리하지 않는다.
                except TimeoutError:
                    pass
        except (WebSocketDisconnect, TimeoutError, RuntimeError):
            return

    web = Path(__file__).parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
