# Korea War Alarm

**English** | [한국어](README.ko.md)

## Know sooner when conflict breaks out on the Korean Peninsula.

**An early-warning monitoring solution for the Korean Peninsula — bringing international reporting, seismic observations, and aviation signals into one continuous monitoring and alerting workflow.**

![Korea War Alarm public-signal monitoring dashboard](docs/assets/dashboard-desktop.png)

[Run on Windows](#run-on-windows) · [Explore the sources](#public-sources) · [API & integrations](docs/API.md)

### Purpose

Korea War Alarm has a specific goal: **help people learn of the outbreak of war or armed attack on the Korean Peninsula as quickly as possible.** It continuously collects public reporting and observations, connects related evidence, and delivers changes through a dashboard and configured notification channels. The focus is the time between information becoming available and reaching the user.

### Collection Strategy

The system prioritizes signals that can be traced to their original sources and cross-validated where possible. It currently combines USGS seismic observations, verified USGS/NEIC observations relayed through EMSC, international news and citizen-journalism sources, and civil-aviation emergency signals from adsb.fi.

Each source is evaluated according to its role and reliability before contributing to an alert decision.

Reports are compared by time, location, and original source. Repeated coverage of one announcement is grouped by provenance, while independent evidence contributes to a rule-based assessment of the incident.

### What it does

- **Continuous collection** — follows public feeds through polling and WebSocket connections.
- **Incident correlation** — connects reports and observations by time, location, and event category, with original-source deduplication.
- **Live dashboard** — displays alert levels, active incidents, supporting evidence, collector health, and processing metrics.
- **Notification and integration** — delivers state changes through desktop notifications, REST, SSE, WebSocket, webhooks, and MQTT.
- **Local operation** — runs the collectors, decision engine, storage, and dashboard on your machine. The Windows bundle includes the runtime.

## Run on Windows

1. Extract the release ZIP.
2. Run `kwa/kwa.exe`.
3. The app creates its default configuration and opens <http://127.0.0.1:8080/>.

Settings, data, and logs are stored in `%LOCALAPPDATA%/KoreaWarAlarm/`.
Press Ctrl+C in the console to shut down. On Windows, closing the console also terminates its child processes.
If port 8080 is occupied, run `kwa.exe launch --port 8081`.
The executable is unsigned; Windows may display a download or SmartScreen warning.

## Public sources

| Source | Role |
|---|---|
| Democracy Now! | Public news RSS |
| Common Dreams | Public news RSS |
| Global Voices | Citizen journalism / OSINT RSS |
| USGS | Seismic observations around the Korean Peninsula |
| EMSC WebSocket | Push transport for reviewed USGS/NEIC seismic solutions |
| adsb.fi | Civil aircraft emergency indications, WATCH only |

All six sources are enabled for new installations. Existing configurations are never overwritten; add the reviewed entries from `config.example.yaml` to opt in.
Reports with unresolved provenance are limited to WATCH and do not count as independent evidence.
CRITICAL requires direct attack reporting, independent high-reliability evidence, and corroboration from physical observations or foreign alerts.

`kwa latency --json` reports local processing intervals separately from observation age. See [Source Layer v2](docs/SOURCE_LAYER_V2.md) for collection architecture and [alert policy](docs/ALERT_POLICY.md) for scoring and source requirements.

The default configuration is for personal, noncommercial local reading. Code is MIT-licensed; source content retains its providers' separate terms.
Release ZIPs contain no collected articles, live databases, or credentials. See [source details and terms](docs/SOURCES.md).

## Run from source

Requires Python 3.12+ and uv. Built WebUI assets are included, so normal use does not require npm.

```powershell
uv sync --locked --extra desktop --extra mqtt --extra dev
uv run kwa launch
```

To choose your configuration directory:

```powershell
uv run kwa init --directory ./local
uv run kwa run --config ./local/config.yaml
```

You can also run `kwa core` and `kwa serve` separately with the same `--config`.
Relative database paths resolve from the configuration file's directory.
The supervisor restarts failed Core/API processes with backoff and exits after repeated failures, leaving diagnostic logs.

## Query and verify

```powershell
curl.exe http://127.0.0.1:8080/api/v1/alert/simple
uv run kwa status --json
uv run kwa alert --json
uv run kwa watch
uv run kwa doctor --config ./local/config.yaml
uv run kwa backup --config ./local/config.yaml --output ./backup.sqlite
uv run kwa replay tests/fixtures/synthetic_attack.json
uv run kwa replay tests/fixtures/historical_dprk_2017.json
```

`doctor` checks configuration and installation prerequisites.
`/api/v1/ready` checks Core heartbeat and enabled-source health, returning HTTP 503 when not ready.
CLI exit codes: normal/INFO/WATCH 0, WARNING 2, HIGH 3, CRITICAL 4, error 10, failed replay 11, doctor not ready 12.

## Develop and build

```powershell
uv sync --locked --extra dev --extra bundle
Push-Location web
npm ci
npm run build
npm test
Pop-Location
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/build_release.py
uv run python scripts/smoke_release.py dist/kwa/kwa.exe
```

Before the first browser test, run `npx playwright install chromium` inside `web/`.
Build Windows, macOS, and Linux bundles on their respective operating systems.
GitHub Actions runs tests and builds OS-specific ZIPs with SHA-256 checksums; version-tag pushes create a draft release.

## Integrations

REST, SSE, WebSocket, optional outbound webhooks, and optional MQTT are available independently of the dashboard.
For an explicitly enabled LAN listener, set your own `KWA_API_TOKEN` environment variable.
This token authenticates access to your local server.
Desktop notifications and a Windows siren are included. Fixture replay never triggers real sound.

[API](docs/API.md) · [Integration examples](docs/INTEGRATIONS.md) · [Alert policy](docs/ALERT_POLICY.md) · [Security](docs/SECURITY.md)
[Implementation details](docs/IMPLEMENTATION.md) · [Verification record](docs/RELEASE_CHECKS.md)
