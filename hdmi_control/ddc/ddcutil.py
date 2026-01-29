import subprocess
import time
from .parser import parse_getvcp, parse_detect, VcpValue
from ..config import CONFIG


class DdcUtilError(RuntimeError):
    pass


class DdcUtil:
    def __init__(self, path: str | None = None):
        self.path = path or CONFIG.ddcutil_path

    def _run(self, args: list[str], timeout_ms: int | None = None) -> str:
        timeout = (timeout_ms or CONFIG.ddc_timeout_ms) / 1000.0
        cmd = [self.path] + args
        try:
            start = time.perf_counter()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            duration_ms = int((time.perf_counter() - start) * 1000)
        except subprocess.TimeoutExpired as exc:
            raise DdcUtilError(f"ddcutil timeout after {timeout_ms}ms") from exc
        if result.returncode != 0:
            raise DdcUtilError(result.stderr.strip() or result.stdout.strip() or "ddcutil error")
        return result.stdout.strip(), duration_ms

    def detect(self) -> tuple[list[dict], int]:
        out, ms = self._run(["detect", "--brief"], timeout_ms=CONFIG.ddc_timeout_ms)
        return parse_detect(out), ms

    def get_vcp(self, code: str, target_args: list[str]) -> tuple[VcpValue, int]:
        out, ms = self._run(["getvcp", code, "--brief"] + target_args)
        return parse_getvcp(out, code), ms

    def set_vcp(self, code: str, value: int, target_args: list[str]) -> int:
        _, ms = self._run(["setvcp", code, str(value)] + target_args)
        return ms
