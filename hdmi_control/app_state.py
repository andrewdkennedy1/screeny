import json
from datetime import datetime
from .db import db_conn


def get_state_value(key: str) -> dict | None:
    with db_conn() as conn:
        row = conn.execute("SELECT value_json FROM app_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def set_state_value(key: str, value: dict) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value), now),
        )
        conn.commit()
