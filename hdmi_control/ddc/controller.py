from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..state import DdcState, now_iso
from ..config import CONFIG
from .ddcutil import DdcUtil, DdcUtilError


@dataclass
class DdcCommandResult:
    ok: bool
    error: str | None
    duration_ms: int | None


class DdcController:
    def __init__(self, state: DdcState, on_update: Callable[[], None], lock: threading.Lock | None = None):
        self.state = state
        self.on_update = on_update
        self.ddcutil = DdcUtil()
        self._state_lock = lock
        self._lock = threading.Lock()
        self._pending: dict[str, int] = {}
        self._wake = threading.Condition(self._lock)
        self._stop = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._target_args: list[str] = []

    def set_on_update(self, on_update: Callable[[], None]) -> None:
        self.on_update = on_update

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._wake.notify_all()

    def set_brightness(self, value: int) -> None:
        self._enqueue("10", value)

    def set_contrast(self, value: int) -> None:
        self._enqueue("12", value)

    def rescan(self) -> None:
        try:
            displays, ms = self.ddcutil.detect()
            if not displays:
                self._set_error("No displays detected")
                return
            display = displays[0]
            self._with_state_lock(lambda: setattr(self.state, "display", display))
            self._select_target(display)
            bright = None
            contrast = None
            ms_b = 0
            ms_c = 0
            bright_err = None
            contrast_err = None
            try:
                bright, ms_b = self.ddcutil.get_vcp("10", self._target_args)
                self._with_state_lock(lambda: self._set_supported("brightness", bright.cur is not None))
            except DdcUtilError:
                bright_err = "Brightness unsupported"
                self._with_state_lock(lambda: self._set_supported("brightness", False))
            try:
                contrast, ms_c = self.ddcutil.get_vcp("12", self._target_args)
                self._with_state_lock(lambda: self._set_supported("contrast", contrast.cur is not None))
            except DdcUtilError:
                contrast_err = "Contrast unsupported"
                self._with_state_lock(lambda: self._set_supported("contrast", False))
            def _apply_scan():
                self.state.supported["vcp"] = [
                    "0x10" if bright and bright.cur is not None else None,
                    "0x12" if contrast and contrast.cur is not None else None,
                ]
                self.state.supported["vcp"] = [v for v in self.state.supported["vcp"] if v]
                if bright:
                    self.state.values["brightness"] = {"cur": bright.cur, "max": bright.max}
                if contrast:
                    self.state.values["contrast"] = {"cur": contrast.cur, "max": contrast.max}
                self.state.status = "ok" if (self.state.supported["brightness"] or self.state.supported["contrast"]) else "degraded"
                if self.state.status == "ok":
                    self.state.lastError = None
                else:
                    self.state.lastError = contrast_err or bright_err or "VCP codes unsupported"
                self.state.lastOkAt = now_iso()
                self.state.lastCommandMs = max(ms_b, ms_c, ms)
            self._with_state_lock(_apply_scan)
            self.on_update()
        except DdcUtilError as exc:
            self._set_error(str(exc))

    def _select_target(self, display: dict) -> None:
        target = CONFIG.ddc_target
        if target == "auto":
            if "bus" in display:
                self._target_args = ["--bus", display["bus"]]
            else:
                self._target_args = []
        elif target.startswith("display:"):
            self._target_args = ["--display", target.split(":", 1)[1]]
        elif target.startswith("bus:"):
            self._target_args = ["--bus", target.split(":", 1)[1]]
        else:
            self._target_args = []

    def _enqueue(self, code: str, value: int) -> None:
        with self._lock:
            self._pending[code] = value
            self._wake.notify_all()

    def _worker(self) -> None:
        while True:
            with self._lock:
                if self._stop:
                    return
                if not self._pending:
                    self._wake.wait(timeout=0.1)
                    continue
                self._wake.wait(timeout=CONFIG.ddc_coalesce_ms / 1000.0)
                pending = dict(self._pending)
                self._pending.clear()
            for code, value in pending.items():
                self._apply(code, value)

    def _apply(self, code: str, value: int) -> DdcCommandResult:
        if code == "10" and not self.state.supported.get("brightness"):
            return DdcCommandResult(False, "Brightness unsupported", None)
        if code == "12" and not self.state.supported.get("contrast"):
            return DdcCommandResult(False, "Contrast unsupported", None)
        max_val = 100
        if code == "10":
            max_val = self.state.values["brightness"].get("max") or 100
        if code == "12":
            max_val = self.state.values["contrast"].get("max") or 100
        value = max(0, min(int(value), int(max_val)))
        retries = CONFIG.ddc_retry_count + 1
        last_error = None
        duration_ms = None
        for _ in range(retries):
            try:
                duration_ms = self.ddcutil.set_vcp(code, value, self._target_args)
                def _apply_ok():
                    if code == "10":
                        self.state.values["brightness"]["cur"] = value
                    if code == "12":
                        self.state.values["contrast"]["cur"] = value
                    self.state.lastOkAt = now_iso()
                    self.state.lastError = None
                    self.state.lastCommandMs = duration_ms
                    self.state.status = "ok"
                self._with_state_lock(_apply_ok)
                self.on_update()
                return DdcCommandResult(True, None, duration_ms)
            except DdcUtilError as exc:
                last_error = str(exc)
                time.sleep(0.05)
        self._set_error(last_error or "DDC failure")
        return DdcCommandResult(False, last_error, duration_ms)

    def _set_error(self, message: str) -> None:
        def _apply_error():
            self.state.status = "degraded" if self.state.display else "unavailable"
            self.state.lastError = message
        self._with_state_lock(_apply_error)
        self.on_update()

    def _with_state_lock(self, fn: Callable[[], None]) -> None:
        if self._state_lock:
            with self._state_lock:
                fn()
        else:
            fn()

    def _set_supported(self, key: str, value: bool) -> None:
        self.state.supported[key] = value
