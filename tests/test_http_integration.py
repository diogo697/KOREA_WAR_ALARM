import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import yaml

from korea_war_alarm.config import Config
from korea_war_alarm.core import Core
from korea_war_alarm.models import Category
from korea_war_alarm.storage import Store


@contextmanager
def process(*args):
    child = subprocess.Popen(
        [sys.executable, "-m", "korea_war_alarm.cli", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        yield child
    finally:
        child.terminate()
        child.wait(timeout=10)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_api(url, child):
    for _ in range(100):
        assert child.poll() is None
        try:
            if httpx.get(url + "/api/v1/health", timeout=0.3).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    raise AssertionError("API did not start")


def test_real_http_sse_reconnect_and_cli(tmp_path, event_factory, monkeypatch):
    monkeypatch.delenv("KWA_API_TOKEN", raising=False)
    config = Config(database=str(tmp_path / "db.sqlite"), sound=False, desktop=False)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), "utf-8")
    store = Store(config.database)
    core = Core(store, config, mode="synthetic")
    core.ingest(event_factory())
    core.ingest(event_factory(1))
    core.ingest(event_factory(2, category=Category.SEISMIC_EVENT, source_type="sensor"))
    expected = store.stream()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    with process("serve", "--config", str(path), "--port", str(port)) as api:
        wait_api(url, api)
        with httpx.Client(base_url=url, timeout=5) as client:
            assert client.get("/").status_code == 200
            assert client.get("/app.js").status_code == 200
            assert client.get("/api/v1/alert/simple").json()["level"] == 4
            for cursor in (0, expected[1]["id"]):
                received = []
                with client.stream(
                    "GET", "/api/v1/stream", headers={"Last-Event-ID": str(cursor)}
                ) as response:
                    for line in response.iter_lines():
                        if line.startswith("id: "):
                            received.append(int(line[4:]))
                        if line.startswith("data: ") and received[-1] == expected[-1]["id"]:
                            break
                assert received == [e["id"] for e in expected if e["id"] > cursor]
        result = subprocess.run(
            [sys.executable, "-m", "korea_war_alarm.cli", "alert", "--json", "--url", url],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 4
        assert json.loads(result.stdout)["level"] == "CRITICAL"
    core.ingest(event_factory(3))
    assert store.alert().seq > 3
    store.close()


def test_core_process_survives_api_exit(tmp_path, monkeypatch):
    monkeypatch.delenv("KWA_API_TOKEN", raising=False)
    config = Config(database=str(tmp_path / "db.sqlite"), sound=False, desktop=False)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), "utf-8")
    port = free_port()
    with process("core", "--config", str(path)) as core:
        with process("serve", "--config", str(path), "--port", str(port)) as api:
            wait_api(f"http://127.0.0.1:{port}", api)
        store = Store(config.database)
        before = store.state("heartbeat")
        for _ in range(30):
            time.sleep(0.1)
            if store.state("heartbeat") != before:
                break
        assert core.poll() is None
        assert store.state("heartbeat") != before
        store.close()
