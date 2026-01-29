# Screeny ? Raspberry Pi HDMI Fullscreen Image Renderer + DDC/CI Control

This project implements a Raspberry Pi?hosted Flask app that drives a fullscreen image renderer and **primary DDC/CI hardware controls** (brightness/contrast) over HDMI.

## Quick Start (Pi OS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### System packages (Pi OS)
```bash
sudo apt install -y libmagic1 python3-pygame
```

### pygame note
`pygame` is installed via apt on Raspberry Pi OS. It is intentionally not pinned in `requirements.txt` to avoid building SDL wheels inside the virtualenv. The renderer will run headless if `pygame` is missing.

### DDC/CI permissions
- Ensure `i2c-dev` is loaded: `sudo modprobe i2c-dev`
- Either:
  - add your user to a group with access to `/dev/i2c-*`, or
  - allow `ddcutil` via sudoers: `myuser ALL=(root) NOPASSWD: /usr/bin/ddcutil *`

### Run
```bash
python -m hdmi_control.app
# in another terminal
python -m renderer.main
```

Open http://127.0.0.1:5000

## Notes
- Renderer uses `pygame` if available. If not installed, it runs in headless mode and logs state updates.
- `DDC_TARGET` can be `auto`, `display:<index>`, or `bus:<busno>`.
- See `systemd/` for service units.
