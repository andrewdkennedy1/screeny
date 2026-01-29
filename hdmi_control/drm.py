import os


DRM_PATH = "/sys/class/drm"


def list_connectors() -> list[dict]:
    connectors = []
    if not os.path.isdir(DRM_PATH):
        return connectors
    for name in os.listdir(DRM_PATH):
        if "-" not in name:
            continue
        status_path = os.path.join(DRM_PATH, name, "status")
        if not os.path.exists(status_path):
            continue
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status = f.read().strip()
        except Exception:
            status = "unknown"
        connectors.append({
            "name": name,
            "status": status,
            "connected": status == "connected",
        })
    connectors.sort(key=lambda c: c["name"])
    return connectors
