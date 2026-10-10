"""SQLite persistence for audit jobs (zero-ops; swap for Postgres when scaling)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.models import AuditResult


class AuditStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, url TEXT, status TEXT, created_at TEXT, data TEXT)"
            )
            self._conn.commit()

    def save(self, result: AuditResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO audits (id, url, status, created_at, data) VALUES (?, ?, ?, ?, ?)",
                (result.id, result.url, result.status.value, result.created_at.isoformat(), result.model_dump_json()),
            )
            self._conn.commit()

    def get(self, audit_id: str) -> AuditResult | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return AuditResult.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, url, status, created_at, json_extract(data, '$.overall_score'), json_extract(data, '$.grade') "
                "FROM audits ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        keys = ("id", "url", "status", "created_at", "overall_score", "grade")
        return [dict(zip(keys, r)) for r in rows]

    def delete(self, audit_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM audits WHERE id = ?", (audit_id,))
            self._conn.commit()
        return cur.rowcount > 0
