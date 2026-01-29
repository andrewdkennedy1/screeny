import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    bind_host: str = os.getenv("BIND_HOST", "0.0.0.0")
    bind_port: int = int(os.getenv("BIND_PORT", "5000"))
    data_dir: str = os.getenv("DATA_DIR", "data")
    db_path: str = os.getenv("DB_PATH", os.path.join("data", "screeny.db"))
    upload_max_mb: int = int(os.getenv("UPLOAD_MAX_MB", "25"))
    auth_token: str | None = os.getenv("AUTH_TOKEN")

    ddcutil_path: str = os.getenv("DDCUTIL_PATH", "/usr/bin/ddcutil")
    ddc_timeout_ms: int = int(os.getenv("DDC_TIMEOUT_MS", "2000"))
    ddc_retry_count: int = int(os.getenv("DDC_RETRY_COUNT", "1"))
    ddc_target: str = os.getenv("DDC_TARGET", "auto")
    ddc_coalesce_ms: int = int(os.getenv("DDC_COALESCE_MS", "75"))

    renderer_url: str = os.getenv("RENDERER_URL", "http://127.0.0.1:5000")

    disable_dpms: bool = os.getenv("DISABLE_DPMS", "1") == "1"


CONFIG = AppConfig()
