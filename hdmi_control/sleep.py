import subprocess
from dataclasses import dataclass


@dataclass
class SleepStatus:
    ok: bool
    output: str | None


def apply_sleep_prevention() -> SleepStatus:
    cmds = [
        ["xset", "s", "off"],
        ["xset", "-dpms"],
        ["xset", "s", "noblank"],
    ]
    outputs = []
    for cmd in cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if result.stdout:
                outputs.append(result.stdout.strip())
        except Exception as exc:
            return SleepStatus(False, str(exc))
    return SleepStatus(True, "\n".join(outputs) if outputs else None)
