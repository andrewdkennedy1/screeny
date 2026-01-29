import os
import json
import magic
from io import BytesIO
from datetime import datetime
from PIL import Image
import ulid

from .config import CONFIG
from .db import db_conn


IMAGE_DIR = os.path.join(CONFIG.data_dir, "images")


def ensure_dirs() -> None:
    os.makedirs(IMAGE_DIR, exist_ok=True)


def list_images() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM images ORDER BY created_at DESC").fetchall()
    columns = ["id", "original_name", "storage_path", "mime_type", "width", "height", "size_bytes", "created_at"]
    return [dict(zip(columns, row)) for row in rows]


def add_image(file_storage) -> dict:
    ensure_dirs()
    raw = file_storage.read()
    size = len(raw)
    if size > CONFIG.upload_max_mb * 1024 * 1024:
        raise ValueError("File too large")
    mime = magic.from_buffer(raw, mime=True)
    if not mime.startswith("image/"):
        raise ValueError("Invalid image type")
    image = Image.open(BytesIO(raw))
    image.load()
    image_id = str(ulid.new())
    ext = os.path.splitext(file_storage.filename or "")[1] or ".img"
    storage_path = os.path.join(IMAGE_DIR, f"{image_id}{ext}")
    with open(storage_path, "wb") as f:
        f.write(raw)
    now = datetime.utcnow().isoformat() + "Z"
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO images (id, original_name, storage_path, mime_type, width, height, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (image_id, file_storage.filename or "", storage_path, mime, image.width, image.height, size, now),
        )
        conn.commit()
    return {
        "id": image_id,
        "original_name": file_storage.filename or "",
        "storage_path": storage_path,
        "mime_type": mime,
        "width": image.width,
        "height": image.height,
        "size_bytes": size,
        "created_at": now,
    }


def delete_image(image_id: str) -> None:
    with db_conn() as conn:
        row = conn.execute("SELECT storage_path FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            return
        storage_path = row[0]
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()
    if storage_path and os.path.exists(storage_path):
        os.remove(storage_path)


def get_image_path(image_id: str) -> str | None:
    with db_conn() as conn:
        row = conn.execute("SELECT storage_path FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        return None
    return row[0]
