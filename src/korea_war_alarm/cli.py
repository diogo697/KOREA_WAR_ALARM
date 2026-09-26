import argparse
import asyncio
import json
import logging
import os
import sys
from urllib.parse import urlsplit

import httpx

from .config import load_config
from .models import Level


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["launch"]
    parser = argparse.ArgumentParser(prog="kwa")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "alert", "incidents", "incident", "sources", "latency", "watch"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--url", default="http://127.0.0.1:8080")
        cmd.add_argument("--json", action="store_true")
        if command == "incident":
            cmd.add_argument("id")
    for command in ("core", "serve", "run", "doctor", "backup"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--config", default="config.yaml")
        if command in {"core", "serve", "run"}:
            cmd.add_argument("--stop-file", help=argparse.SUPPRESS)
        if command in {"serve", "run"}:
            cmd.add_argument("--host", default="127.0.0.1")
            cmd.add_argument("--port", default=8080, type=int)
        if command == "backup":
            cmd.add_argument("--output", required=True)
    cmd = sub.add_parser("init")
    cmd.add_argument("--directory", default=".")
    cmd = sub.add_parser("launch")
    cmd.add_argument("--directory")
    cmd.add_argument("--port", type=int, default=8080)
    cmd.add_argument("--no-browser", action="store_true")
    cmd = sub.add_parser("replay")
    cmd.add_argument("fixture")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.command == "launch":
            from .deployment import launch

            return launch(args.directory, args.port, args.no_browser)
        if args.command == "init":
            from .deployment import initialize

            print(json.dumps({"config": str(initialize(args.directory))}))
            return 0
        if args.command == "run":
            from .deployment import run

            return run(args.config, args.host, args.port, args.stop_file)
        if args.command == "doctor":
            from .deployment import doctor

            result = doctor(load_config(args.config))
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["operational_ready"] else 12
        if args.command == "backup":
            from .deployment import backup

            backup(load_config(args.config), args.output)
            print(json.dumps({"backup": args.output}))
            return 0
        if args.command == "core":
            from .deployment import configure_logs
            from .runtime import run_core

            config = load_config(args.config)
            configure_logs(config, "core")
            asyncio.run(run_core(config, args.stop_file))
            return 0
        if args.command == "serve":
            from .deployment import configure_logs, serve

            config = load_config(args.config)
            configure_logs(config, "api")
            asyncio.run(serve(config, args.host, args.port, args.stop_file))
            return 0
        if args.command == "replay":
            from .replay import replay

            result = replay(args.fixture)
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 11
        headers = {}
        if token := os.environ.get("KWA_API_TOKEN"):
            target = urlsplit(args.url)
            if target.scheme != "https" and not (
                target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("authenticated external requests require HTTPS")
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(base_url=args.url, headers=headers, timeout=10) as client:
            if args.command == "watch":
                cursor = "0"
                while True:
                    try:
                        with client.stream(
                            "GET",
                            "/api/v1/stream",
                            headers={"Last-Event-ID": cursor},
                            timeout=httpx.Timeout(15, connect=5),
                        ) as response:
                            response.raise_for_status()
                            for line in response.iter_lines():
                                if line.startswith("id: "):
                                    cursor = line[4:]
                                if line.startswith("data: "):
                                    print(
                                        json.dumps(json.loads(line[6:]), ensure_ascii=True),
                                        flush=True,
                                    )
                    except httpx.TransportError:
                        import time

                        time.sleep(2)
            route = "incidents/" + args.id if args.command == "incident" else args.command
            response = client.get("/api/v1/" + route)
            response.raise_for_status()
            payload = response.json()
            print(json.dumps(payload, ensure_ascii=True, indent=None if args.json else 2))
            if args.command == "alert":
                return max(
                    0, Level(payload["level"]).rank if Level(payload["level"]).rank >= 2 else 0
                )
            return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "hint": "Check configuration, required environment variables and local logs.",
                }
            ),
            file=sys.stderr,
        )
        return 10


if __name__ == "__main__":
    sys.exit(main())
