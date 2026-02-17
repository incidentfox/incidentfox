from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class SummaryCacheKey:
    model_id: str
    layer: int
    max_tokens: int
    context_sha256: str


class SummaryCache:
    """
    Persistent summary cache (SQLite).

    Keyed by (model_id, layer, max_tokens, sha256(context)).
    Thread-safe for concurrent reads/writes within a single process.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tls = threading.local()

        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
              model_id TEXT NOT NULL,
              layer INTEGER NOT NULL,
              max_tokens INTEGER NOT NULL,
              context_sha256 TEXT NOT NULL,
              summary TEXT NOT NULL,
              PRIMARY KEY (model_id, layer, max_tokens, context_sha256)
            );
            """)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=30)
            c.execute("PRAGMA journal_mode=WAL;")
            self._tls.conn = c
        return c

    def get(self, key: SummaryCacheKey) -> Optional[str]:
        with self._lock:
            cur = self._conn().execute(
                "SELECT summary FROM summaries WHERE model_id=? AND layer=? AND max_tokens=? AND context_sha256=?",
                (key.model_id, int(key.layer), int(key.max_tokens), key.context_sha256),
            )
            row = cur.fetchone()
        if not row:
            return None
        val = row[0]
        return val if isinstance(val, str) else None

    def put(self, key: SummaryCacheKey, summary: str) -> None:
        s = (summary or "").strip()
        if not s:
            return
        with self._lock:
            self._conn().execute(
                "INSERT OR REPLACE INTO summaries(model_id, layer, max_tokens, context_sha256, summary) VALUES (?,?,?,?,?)",
                (
                    key.model_id,
                    int(key.layer),
                    int(key.max_tokens),
                    key.context_sha256,
                    s,
                ),
            )
            self._conn().commit()

    @staticmethod
    def make_key(
        *, model_id: str, layer: int, max_tokens: int, context: str
    ) -> SummaryCacheKey:
        return SummaryCacheKey(
            model_id=str(model_id),
            layer=int(layer),
            max_tokens=int(max_tokens),
            context_sha256=_sha256_text(context or ""),
        )
