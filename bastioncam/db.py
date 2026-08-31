from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS panes (
  id INTEGER PRIMARY KEY,
  collector_id TEXT,
  session_name TEXT NOT NULL,
  pane_key TEXT NOT NULL,
  tab_name TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  command TEXT NOT NULL DEFAULT '',
  cwd TEXT NOT NULL DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE(session_name, pane_key)
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  pane_id INTEGER NOT NULL REFERENCES panes(id),
  captured_at TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  summary TEXT,
  embedding TEXT,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS snapshots_time ON snapshots(captured_at);
CREATE INDEX IF NOT EXISTS snapshots_pane_time ON snapshots(pane_id, captured_at);
CREATE VIRTUAL TABLE IF NOT EXISTS snapshots_fts USING fts5(
  content, summary, content='snapshots', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS snapshots_ai AFTER INSERT ON snapshots BEGIN
  INSERT INTO snapshots_fts(rowid, content, summary)
  VALUES (new.id, new.content, coalesce(new.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS snapshots_ad AFTER DELETE ON snapshots BEGIN
  INSERT INTO snapshots_fts(snapshots_fts, rowid, content, summary)
  VALUES ('delete', old.id, old.content, coalesce(old.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS snapshots_au AFTER UPDATE OF content, summary ON snapshots BEGIN
  INSERT INTO snapshots_fts(snapshots_fts, rowid, content, summary)
  VALUES ('delete', old.id, old.content, coalesce(old.summary, ''));
  INSERT INTO snapshots_fts(rowid, content, summary)
  VALUES (new.id, new.content, coalesce(new.summary, ''));
END;
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY,
  pane_id INTEGER NOT NULL REFERENCES panes(id),
  first_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  last_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  source_text TEXT NOT NULL,
  summary TEXT,
  embedding TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(pane_id, first_snapshot_id, last_snapshot_id)
);
CREATE INDEX IF NOT EXISTS segments_time ON segments(started_at, ended_at);
CREATE INDEX IF NOT EXISTS segments_status ON segments(status, id);
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
  source_text, summary, content='segments', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
  INSERT INTO segments_fts(rowid, source_text, summary)
  VALUES (new.id, new.source_text, coalesce(new.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, source_text, summary)
  VALUES ('delete', old.id, old.source_text, coalesce(old.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE OF source_text, summary ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, source_text, summary)
  VALUES ('delete', old.id, old.source_text, coalesce(old.summary, ''));
  INSERT INTO segments_fts(rowid, source_text, summary)
  VALUES (new.id, new.source_text, coalesce(new.summary, ''));
END;
CREATE TABLE IF NOT EXISTS period_summaries (
  id INTEGER PRIMARY KEY,
  period_type TEXT NOT NULL CHECK(period_type IN ('hour','day')),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  segment_count INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(period_type, period_start)
);
CREATE INDEX IF NOT EXISTS period_summaries_recent
  ON period_summaries(period_type, period_start DESC);
CREATE TABLE IF NOT EXISTS server_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collectors (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  last_seen_at TEXT,
  disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_expiry ON web_sessions(expires_at);
-- Recover rows produced by older Qwen thinking-mode responses, where the API
-- returned an empty response while the useful text went to a separate field.
UPDATE segments SET status='retry',summary=NULL,embedding=NULL
  WHERE status='done' AND trim(coalesce(summary,''))='';
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(snapshots)")}
    if "delivered_at" not in columns:
        db.execute("ALTER TABLE snapshots ADD COLUMN delivered_at TEXT")
    pane_columns = {row[1] for row in db.execute("PRAGMA table_info(panes)")}
    if "collector_id" not in pane_columns:
        db.execute("ALTER TABLE panes ADD COLUMN collector_id TEXT")
    return db


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return dot / norm if norm else 0.0


def decode_embedding(value: str | None) -> list[float]:
    return json.loads(value) if value else []
