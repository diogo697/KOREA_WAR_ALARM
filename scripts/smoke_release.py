"""패키징된 실행 파일을 빈 폴더에서 검증한다. 브라우저·소리는 열지 않는다."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml


def main():
    executable = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="kwa-package-test-") as temporary:
        root = Path(temporary)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        environment = dict(os.environ)
        environment.pop("KWA_API_TOKEN", None)

        def call(*args):
            return subprocess.run(
                [executable, *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=flags,
                env=environment,
            )

        result = call("init")
        assert result.returncode == 0, result.stderr
        config = root / "config.yaml"
        values = yaml.safe_load(config.read_text("utf-8"))
        assert len(values["sources"]) == 6
        live = "--live" in sys.argv
        if not live:
            values["sources"] = []
        values["desktop"] = values["sound"] = False
        config.write_text(yaml.safe_dump(values), "utf-8")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        stop = root / "stop"
        with (root / "run.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [executable, "run", "--port", str(port), "--stop-file", str(stop)],
                cwd=root,
                stdout=log,
                stderr=log,
                creationflags=flags,
                env=environment,
            )
            try:
                url = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=url, timeout=2) as client:
                    for _ in range(120):
                        if process.poll() is not None:
                            raise AssertionError((root / "run.log").read_text("utf-8"))
                        try:
                            response = client.get("/api/v1/status")
                            if (
                                response.status_code == 200
                                and response.json()["status"] == "running"
                            ):
                                if not live or client.get("/api/v1/ready").status_code == 200:
                                    break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.25)
                    else:
                        raise AssertionError("packaged API failed to start")
                    assert client.get("/").status_code == 200
                    assert client.get("/app.js").status_code == 200
                    level = client.get("/api/v1/alert/simple").json()["level"]
                    assert isinstance(level, int) and 0 <= level <= 4
                    if not live:
                        assert level == 0
                    if "--capture" in sys.argv:
                        project = Path(__file__).resolve().parents[1]
                        subprocess.run(
                            ["node", str(project / "web/scripts/capture.mjs"), url],
                            cwd=project,
                            check=True,
                            timeout=60,
                            creationflags=flags,
                        )
                    result = call("status", "--url", url, "--json")
                    assert result.returncode == 0, result.stderr
                    assert call("backup", "--output", "backup.sqlite").returncode == 0
            finally:
                stop.touch()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
            assert process.returncode == 0, (root / "run.log").read_text("utf-8")
        print(
            json.dumps(
                {
                    "packaged_smoke": "passed",
                    "live_public_sources": live,
                    "executable": executable,
                    "checks": [
                        "first-run config",
                        "supervisor",
                        "core heartbeat",
                        "REST",
                        "WebUI assets",
                        "CLI",
                        "backup",
                        "graceful shutdown",
                    ],
                }
            )
        )


if __name__ == "__main__":
    main()
