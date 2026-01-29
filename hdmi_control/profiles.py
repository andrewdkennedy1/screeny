import json
from datetime import datetime
from ulid import ULID
from .db import db_conn


def list_profiles() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute("SELECT id, name, data_json, is_default, created_at, updated_at FROM profiles ORDER BY updated_at DESC").fetchall()
    profiles = []
    for row in rows:
        profiles.append({
            "id": row[0],
            "name": row[1],
            "data": json.loads(row[2]),
            "is_default": bool(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
        })
    return profiles


def create_profile(name: str, data: dict) -> dict:
    profile_id = str(ULID())
    now = datetime.utcnow().isoformat() + "Z"
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name, data_json, is_default, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (profile_id, name, json.dumps(data), now, now),
        )
        conn.commit()
    return {"id": profile_id, "name": name, "data": data, "is_default": False}


def update_profile(profile_id: str, name: str | None, data: dict | None) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    with db_conn() as conn:
        if name is not None:
            conn.execute("UPDATE profiles SET name = ?, updated_at = ? WHERE id = ?", (name, now, profile_id))
        if data is not None:
            conn.execute("UPDATE profiles SET data_json = ?, updated_at = ? WHERE id = ?", (json.dumps(data), now, profile_id))
        conn.commit()


def delete_profile(profile_id: str) -> None:
    with db_conn() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.commit()


def set_default_profile(profile_id: str) -> None:
    with db_conn() as conn:
        conn.execute("UPDATE profiles SET is_default = 0")
        conn.execute("UPDATE profiles SET is_default = 1 WHERE id = ?", (profile_id,))
        conn.commit()


def get_profile(profile_id: str) -> dict | None:
    with db_conn() as conn:
        row = conn.execute("SELECT id, name, data_json, is_default, created_at, updated_at FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "data": json.loads(row[2]),
        "is_default": bool(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
    }


def load_default_or_last() -> str | None:
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
        if row:
            return row[0]
        row = conn.execute("SELECT id FROM profiles ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row:
            return row[0]
    return None
