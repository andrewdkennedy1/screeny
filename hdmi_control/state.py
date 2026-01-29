from __future__ import annotations
import json
import time
from dataclasses import dataclass, field


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class DdcState:
    status: str = "unavailable"
    display: dict = field(default_factory=dict)
    supported: dict = field(default_factory=lambda: {"brightness": False, "contrast": False, "vcp": []})
    values: dict = field(default_factory=lambda: {
        "brightness": {"cur": None, "max": None},
        "contrast": {"cur": None, "max": None},
    })
    lastError: str | None = None
    lastOkAt: str | None = None
    lastCommandMs: int | None = None


@dataclass
class RenderState:
    transform: dict = field(default_factory=lambda: {
        "mode": "fit",
        "scale": 1.0,
        "rotationDeg": 0,
        "flipH": False,
        "flipV": False,
        "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        "pan": {"x": 0.0, "y": 0.0},
    })
    color: dict = field(default_factory=lambda: {
        "brightness": 0.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "hue": 0.0,
        "gamma": 1.0,
        "temperature": 0.0,
        "tint": 0.0,
    })
    output: dict = field(default_factory=lambda: {
        "background": "#000000",
        "interpolation": "linear",
        "fullscreen": True,
    })


@dataclass
class SystemState:
    activeProfileId: str | None = None
    activeImageId: str | None = None
    ddc: DdcState = field(default_factory=DdcState)
    render: RenderState = field(default_factory=RenderState)
    meta: dict = field(default_factory=lambda: {"version": 1, "updatedAt": now_iso()})

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self, default=lambda o: o.__dict__))

    def bump(self) -> None:
        self.meta["version"] += 1
        self.meta["updatedAt"] = now_iso()
