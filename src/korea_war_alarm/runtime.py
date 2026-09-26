import asyncio
import json
import logging
from contextlib import contextmanager
from pathlib import Path

import httpx

from .alerts import alert_worker, webhook_worker
from .collectors import make_collector
from .config import Config
from .core import Core
from .models import SourceHealth, utcnow
from .storage import Store


async def supervise_worker(name, factory):
    failures = 0
    while True:
        try:
            await factory()
            raise RuntimeError("worker returned unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            logging.getLogger("kwa.core").error(
                json.dumps(
                    {
                        "event": "worker.restart",
                        "worker": name,
                        "error": type(exc).__name__,
                        "failures": failures,
                    }
                )
            )
            await asyncio.sleep(min(60, 2 ** min(failures, 6)))


@contextmanager
def core_lock(database: str):
    path = Path(database + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            import sys

            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("a core process already owns this database") from exc
        yield


async def run_core(config: Config, stop_file: str | None = None):
    with core_lock(config.database):
        store = Store(config.database)
        core = Core(store, config)
        with store.db:
            store.db.execute("DELETE FROM sources")
        tasks = []
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=False,
                headers={"User-Agent": "KoreaWarAlarm/0.1 (public-feed monitor)"},
            ) as client:
                for source in config.sources:
                    store.health(
                        SourceHealth(
                            source_id=source.id,
                            enabled=source.enabled,
                            poll_seconds=source.poll_seconds,
                            signal_type=source.signal_type,
                            evidence_family=source.evidence_family,
                            stale_after_seconds=source.stale_after_seconds,
                        )
                    )
                    if source.enabled:
                        collector = make_collector(source, core.ingest, store.health, client)
                        tasks.append(
                            asyncio.create_task(supervise_worker(source.id, collector.start))
                        )
                tasks.append(
                    asyncio.create_task(supervise_worker("local", lambda: alert_worker(config)))
                )
                tasks.append(
                    asyncio.create_task(supervise_worker("webhook", lambda: webhook_worker(config)))
                )
                if config.mqtt.enabled:
                    from .mqtt import mqtt_worker

                    tasks.append(
                        asyncio.create_task(supervise_worker("mqtt", lambda: mqtt_worker(config)))
                    )
                count = 0
                while not (stop_file and Path(stop_file).exists()):
                    core.tick()
                    if count % 3600 == 0:
                        store.prune(config.retention_days, utcnow())
                    count += 1
                    await asyncio.sleep(1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with store.db:
                store.set_state("heartbeat", "1970-01-01T00:00:00+00:00")
            store.close()
