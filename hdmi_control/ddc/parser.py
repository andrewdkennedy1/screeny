import re
from dataclasses import dataclass


@dataclass
class VcpValue:
    code: str
    cur: int | None
    max: int | None


_VCP_RE = re.compile(r"current value = (\d+), max value = (\d+)")
_VCP_BRIEF_RE = re.compile(r"VCP\s+([0-9A-Fa-f]{2})\s+[A-Z]\s+(\d+)\s+(\d+)")


def parse_getvcp(output: str, code: str) -> VcpValue:
    match = _VCP_RE.search(output)
    if not match:
        match = _VCP_BRIEF_RE.search(output)
        if not match:
            return VcpValue(code=code, cur=None, max=None)
        return VcpValue(code=code, cur=int(match.group(2)), max=int(match.group(3)))
    return VcpValue(code=code, cur=int(match.group(1)), max=int(match.group(2)))


def parse_detect(output: str) -> list[dict]:
    displays: list[dict] = []
    current: dict | None = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Display"):
            if current:
                displays.append(current)
            parts = line.split()
            index = parts[1] if len(parts) > 1 else None
            current = {"raw": [], "index": index}
        if current is not None:
            current["raw"].append(line)
            if line.startswith("I2C bus:"):
                raw_bus = line.split(":", 1)[1].strip()
                if raw_bus.startswith("/dev/i2c-"):
                    raw_bus = raw_bus.split("/dev/i2c-")[-1]
                current["bus"] = raw_bus
            if line.startswith("EDID synopsis:"):
                current["edid"] = line.split(":", 1)[1].strip()
            if line.startswith("Model:"):
                current["model"] = line.split(":", 1)[1].strip()
            if line.startswith("Serial number:"):
                current["serial"] = line.split(":", 1)[1].strip()
            if line.startswith("DRM connector:"):
                current["connector"] = line.split(":", 1)[1].strip()
    if current:
        displays.append(current)
    return displays
