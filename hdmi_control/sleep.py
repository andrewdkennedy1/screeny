import os
import subprocess
import getpass
from dataclasses import dataclass


@dataclass
class SleepStatus:
    ok: bool
    output: str | None


def apply_sleep_prevention() -> SleepStatus:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", f"/home/{getpass.getuser()}/.Xauthority")
    cmds = [
        ["xset", "s", "off"],
        ["xset", "-dpms"],
        ["xset", "s", "noblank"],
    ]
    outputs = []
    for cmd in cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            if result.stdout:
                outputs.append(result.stdout.strip())
        except Exception as exc:
            # Fallback for console/KMS setups
            try:
                result = subprocess.run(
                    ["setterm", "-blank", "0", "-powerdown", "0", "-powersave", "off"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.stdout:
                    outputs.append(result.stdout.strip())
                return SleepStatus(True, "\n".join(outputs) if outputs else None)
            except Exception:
                return SleepStatus(False, str(exc))
    return SleepStatus(True, "\n".join(outputs) if outputs else None)
