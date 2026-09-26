import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import Alert, Event, Incident, SourceHealth, utcnow


class Store:
    def __init__(self, path: str, *, read_only: bool = False):
        if read_only:
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self.db = sqlite3.connect(uri, uri=True, timeout=2, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            return
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, received_at TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS stream (
                id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, payload TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS deliveries (
                id TEXT PRIMARY KEY, target INTEGER, payload TEXT, attempts INTEGER DEFAULT 0,
                next_attempt REAL DEFAULT 0, status TEXT DEFAULT 'pending');
        """)
        self.db.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(deliveries)")}
        for name in ("destination", "context"):
            if name not in columns:
                self.db.execute(f"ALTER TABLE deliveries ADD COLUMN {name} TEXT")
        with self.db:
            self.db.execute("CREATE INDEX IF NOT EXISTS event_age ON events(received_at)")
            self.db.execute("CREATE INDEX IF NOT EXISTS stream_age ON stream(created_at)")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS delivery_queue ON deliveries(status,next_attempt)"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS incident_active ON incidents(json_extract(payload,'$.active'))"
            )
            self.db.execute("PRAGMA user_version=1")
            if self.state("alert") is None:
                self.set_state("alert", Alert().model_dump(mode="json"))

    def close(self):
        self.db.close()

    def state(self, key: str, default=None):
        row = self.db.execute("SELECT payload FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def alert(self) -> Alert:
        return Alert.model_validate(self.state("alert", {}))

    def incidents(self, *, active: bool | None = None, limit: int | None = None) -> list[Incident]:
        query = "SELECT payload FROM incidents"
        parameters = []
        if active is not None:
            query += " WHERE json_extract(payload,'$.active')=?"
            parameters.append(int(active))
        query += " ORDER BY json_extract(payload,'$.updated_at') DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        return [Incident.model_validate_json(r[0]) for r in self.db.execute(query, parameters)]

    def incident(self, incident_id: str) -> Incident | None:
        row = self.db.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return Incident.model_validate_json(row[0]) if row else None

    def delivery_counts(self) -> dict[str, int]:
        return dict(
            self.db.execute("SELECT status,COUNT(*) FROM deliveries GROUP BY status").fetchall()
        )

    def save_incident(self, incident: Incident):
        self.db.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?)",
            (incident.id, incident.model_dump_json()),
        )

    def add_event(self, event: Event) -> bool:
        return (
            self.db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?)",
                (
                    event.id,
                    event.fingerprint,
                    event.received_at.isoformat(),
                    event.model_dump_json(),
                ),
            ).rowcount
            == 1
        )

    def emit(self, kind: str, payload: dict) -> int:
        cursor = self.db.execute(
            "INSERT INTO stream(type,payload,created_at) VALUES (?,?,?)",
            (kind, json.dumps(payload), utcnow().isoformat()),
        )
        return cursor.lastrowid

    def stream(self, after: int = 0, limit: int = 200) -> list[dict]:
        return [
            {"id": r[0], "event": r[1], "data": json.loads(r[2])}
            for r in self.db.execute(
                "SELECT id,type,payload FROM stream WHERE id>? ORDER BY id LIMIT ?", (after, limit)
            )
        ]

    def health(self, value: SourceHealth):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sources VALUES (?,?)",
                (value.source_id, value.model_dump_json()),
            )
            self.emit("source.health_changed", value.model_dump(mode="json"))

    def sources(self) -> list[SourceHealth]:
        return [
            SourceHealth.model_validate_json(r[0])
            for r in self.db.execute("SELECT payload FROM sources ORDER BY id")
        ]

    def prune(self, days: int, now: datetime):
        cutoff = (now - timedelta(days=days)).isoformat()
        with self.db:
            self.db.execute("DELETE FROM events WHERE received_at<?", (cutoff,))
            self.db.execute("DELETE FROM stream WHERE created_at<?", (cutoff,))
            for incident in self.incidents():
                if not incident.active and incident.updated_at < now - timedelta(days=days):
                    self.db.execute("DELETE FROM incidents WHERE id=?", (incident.id,))
            self.db.execute("DELETE FROM deliveries WHERE status='delivered'")
