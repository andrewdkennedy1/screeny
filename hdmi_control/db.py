import os
import sqlite3
from contextlib import contextmanager
from .config import CONFIG


SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY,
  original_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  data_json TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ddc_cache (
  id TEXT PRIMARY KEY,
  display_identity_json TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def init_db() -> None:
    os.makedirs(os.path.dirname(CONFIG.db_path), exist_ok=True)
    with sqlite3.connect(CONFIG.db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def db_conn():
    conn = sqlite3.connect(CONFIG.db_path)
    try:
        yield conn
    finally:
        conn.close()
