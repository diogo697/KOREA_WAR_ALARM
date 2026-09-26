import asyncio
import json
import logging
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Config, load_config
from .storage import Store

DEFAULT_CONFIG = """# Korea War Alarm - monitoring configuration
database: data/kwa.sqlite
threshold: HIGH
desktop: true
sound: true
sources:
  - id: democracy-now
    publisher: Democracy Now!
    url: https://www.democracynow.org/democracynow.rss
    operator_country: US
    source_type: news
    reliability: 0.8
    enabled: true
    terms_reviewed: true
    license_url: https://creativecommons.org/licenses/by-nc-nd/3.0/us/
  - id: common-dreams
    publisher: Common Dreams
    url: https://www.commondreams.org/feeds/feed.rss
    operator_country: US
    source_type: news
    reliability: 0.75
    enabled: true
    terms_reviewed: true
    license_url: https://www.commondreams.org/republish-our-work
  - id: global-voices
    publisher: Global Voices
    url: https://globalvoices.org/feed/
    operator_country: NL
    source_type: osint
    signal_type: OSINT
    reliability: 0.7
    poll_seconds: 300
    enabled: true
    terms_reviewed: true
    license_url: https://creativecommons.org/licenses/by/3.0/
  - id: usgs
    publisher: USGS
    url: https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson
    operator_country: US
    government: true
    kind: usgs
    source_type: sensor
    signal_type: SEISMIC
    evidence_family: usgs
    stale_after_seconds: 180
    reliability: 0.95
    poll_seconds: 60
    enabled: true
    terms_reviewed: true
  - id: emsc-push
    publisher: EMSC/CSEM
    url: wss://www.seismicportal.eu/standing_order/websocket
    operator_country: FR
    kind: emsc_ws
    source_type: sensor
    signal_type: SEISMIC
    evidence_family: usgs
    reliability: 0.95
    poll_seconds: 30
    min_poll_seconds: 15
    enabled: true
    terms_reviewed: true
    license_url: https://www.seismicportal.eu/realtime.html
  - id: adsb-fi
    publisher: adsb.fi
    url: https://opendata.adsb.fi/api/v3/lat/37.5/lon/127/dist/250
    operator_country: UNKNOWN
    kind: adsb
    source_type: sensor
    signal_type: AVIATION
    evidence_family: adsb-receiver-network
    reliability: 0.5
    poll_seconds: 30
    min_poll_seconds: 5
    stale_after_seconds: 120
    enabled: true
    terms_reviewed: true
    license_url: https://github.com/adsbfi/opendata
webhooks: []
"""


def initialize(directory: str) -> Path:
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    path = target / "config.yaml"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(DEFAULT_CONFIG)
    return path


def configure_logs(config: Config, name: str):
    folder = Path(config.database).parent / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / f"{name}.log", maxBytes=config.log_max_bytes, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def validate_bind(config: Config, host: str):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("bind to loopback; external access requires an HTTPS reverse proxy")


def self_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "korea_war_alarm.cli", *args]


async def serve(config: Config, host: str, port: int, stop_file: str | None = None):
    import uvicorn

    from .api import create_app

    validate_bind(config, host)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config), host=host, port=port, access_log=False, timeout_graceful_shutdown=5
        )
    )

    async def monitor():
        while not server.should_exit:
            if stop_file and Path(stop_file).exists():
                server.should_exit = True
                return
            await asyncio.sleep(0.2)

    watcher = asyncio.create_task(monitor())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def run(config_path: str, host: str, port: int, stop_file: str | None = None) -> int:
    from .windows_job import ProcessJob

    config_path = str(Path(config_path).resolve())
    config = load_config(config_path)
    validate_bind(config, host)
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
        probe.bind((host, port))
    configure_logs(config, "supervisor")
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    children = {}
    failures = {"core": 0, "serve": 0}
    retry_at = {"core": 0.0, "serve": 0.0}
    started = {}
    job = ProcessJob()
    try:
        with tempfile.TemporaryDirectory(prefix="kwa-run-") as folder:
            stop_path = Path(folder) / "stop"
            try:
                while not stopping and not (stop_file and Path(stop_file).exists()):
                    for name in failures:
                        child = children.get(name)
                        if child and child.poll() is not None:
                            if time.monotonic() - started[name] > 60:
                                failures[name] = 0
                            failures[name] += 1
                            if failures[name] > 5:
                                raise RuntimeError(f"{name} repeatedly failed; inspect local logs")
                            logging.getLogger("kwa.supervisor").warning(
                                json.dumps(
                                    {
                                        "event": "process.restart",
                                        "worker": name,
                                        "exit": child.returncode,
                                    }
                                )
                            )
                            retry_at[name] = time.monotonic() + min(30, 2 ** failures[name])
                            children.pop(name)
                        if name not in children and time.monotonic() >= retry_at[name]:
                            args = [name, "--config", config_path, "--stop-file", str(stop_path)]
                            if name == "serve":
                                args += ["--host", host, "--port", str(port)]
                            children[name] = subprocess.Popen(
                                self_command(*args),
                                creationflags=subprocess.CREATE_NO_WINDOW
                                if sys.platform == "win32"
                                else 0,
                            )
                            job.add(children[name])
                            started[name] = time.monotonic()
                    time.sleep(0.2)
            finally:
                stop_path.touch()
                deadline = time.monotonic() + 10
                for child in children.values():
                    try:
                        child.wait(timeout=max(0.1, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        child.wait(timeout=5)
    finally:
        job.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


def launch(directory: str | None, port: int, no_browser: bool = False) -> int:
    import threading
    import webbrowser

    import httpx

    root = (
        Path(directory)
        if directory
        else Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        / "KoreaWarAlarm"
    )
    path = root / "config.yaml"
    if not path.exists():
        path = initialize(str(root))
    if not no_browser:

        def open_when_ready():
            for _ in range(100):
                try:
                    if (
                        httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5).status_code
                        == 200
                    ):
                        webbrowser.open(f"http://127.0.0.1:{port}/")
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.2)

        threading.Thread(target=open_when_ready, daemon=True).start()
    return run(str(path), "127.0.0.1", port)


def doctor(config: Config) -> dict:
    blockers = []
    for hook in config.webhooks:
        if not os.environ.get(hook.secret_env):
            blockers.append(f"missing environment variable: {hook.secret_env}")
    if config.desktop:
        import importlib.util

        if importlib.util.find_spec("plyer") is None:
            blockers.append("desktop extra not installed")
    if config.mqtt.enabled:
        try:
            import paho.mqtt.client  # noqa: F401
        except ImportError:
            blockers.append("MQTT extra not installed")
    if not any(s.enabled for s in config.sources):
        blockers.append("no public sources enabled")
    return {
        "configuration_valid": True,
        "operational_ready": not blockers,
        "critical_capable": config.critical_capable(),
        "warnings": []
        if config.critical_capable()
        else ["Current sources cannot satisfy CRITICAL/siren requirements."],
        "database": config.database,
        "enabled_sources": [s.id for s in config.sources if s.enabled],
        "blockers": blockers,
    }


def backup(config: Config, destination: str):
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb"):
        pass
    source = Store(config.database, read_only=True)
    try:
        with sqlite3.connect(target) as output:
            source.db.backup(output)
    finally:
        source.close()
