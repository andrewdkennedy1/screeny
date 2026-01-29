# spec.md ? Raspberry Pi HDMI Fullscreen Image Renderer + DDC/CI Hardware Control (Flask)

## 1. Purpose

Build a Raspberry Pi-hosted Python/Flask application that:

1) Renders a fullscreen image on an HDMI-connected display (monitor/TV), with live image transforms and color adjustments.
2) Provides primary, first-class control of the display's hardware settings via DDC/CI (at minimum: brightness and contrast), including:
   - Live slider control from a responsive Web UI
   - Capability detection (supported VCP codes, ranges)
   - Robust bus detection and monitor selection
   - Presets/profiles that persist across reboot
3) Ensures no screen sleep/blanking.

Key constraint: DDC/CI control is the main focus. The image renderer is integrated, but hardware brightness/contrast control must be reliable and observable.

---

## 2. Definitions / Background

- DDC/CI: Display Data Channel / Command Interface. A protocol (typically over I2C lines embedded in HDMI/DP) allowing software to query/set monitor settings using VCP codes.
- VCP 0x10: Luminance / brightness (commonly supported)
- VCP 0x12: Contrast (commonly supported)
- Tooling:
  - ddcutil (Linux) is the reference implementation for querying/setting VCP.
  - Kernel modules: i2c-dev is typically required.

---

## 3. Scope

### 3.1 In Scope
- DDC/CI discovery + control over HDMI (and DP if relevant to hardware path)
- Live hardware adjustments: brightness/contrast (required), plus optional best-effort support for additional VCP features if present (gamma, RGB gains, color temp modes, etc.)
- Fullscreen image display on HDMI
- Upload image from Web UI; apply transforms (scale/crop/pan/rotate) and pixel-level color (software pipeline)
- Saved profiles containing:
  - DDC/CI hardware settings
  - Render settings
  - Active image selection
- Persistence, boot restore, and screen blank prevention
- Systemd services and operational hardening

### 3.2 Out of Scope
- Video playback
- Multi-display compositor features (single intended output; multi-monitor support may exist but is not required)
- Mobile native app (Web UI only)

---

## 4. Target Platform and Assumptions

- Raspberry Pi OS (Debian-based), 64-bit preferred
- Python 3.11+
- Display connected via HDMI to the Pi
- Network access for Web UI over LAN

### 4.1 Known Real-World Constraints (Must Handle)
- Some monitors only accept DDC/CI commands on the currently active input.
- Certain adapters/switches/KVMs can block DDC.
- Some monitors support brightness but not contrast (or vice versa).
- DDC/CI may be disabled in the monitor's OSD ("DDC/CI: Off").

---

## 5. Primary User Stories

1) As a user, I open the Web UI and move a Brightness slider; the monitor's hardware brightness changes immediately.
2) As a user, I can see whether DDC/CI is connected, which bus is used, and whether the monitor supports the requested setting.
3) As a user, I can create a "Night" profile (lower brightness, different crop/scale) and apply it instantly.
4) After reboot, the system restores the last active profile (or configured default) and keeps the screen awake.

---

## 6. High-Level Architecture

### 6.1 Components
1) Flask App (API + Web UI + WebSocket)
2) DDC Controller (hardware control subsystem)
3) Renderer (fullscreen image display subsystem)
4) Persistence Layer (SQLite + filesystem)
5) Supervisor/Services (systemd units)

### 6.2 Process Topology
Recommended: two processes
- hdmi-control-web (Flask + WS + persistence + orchestration)
- hdmi-control-render (fullscreen renderer)

DDC control can run inside the Flask process, but must be isolated behind a single threaded command queue to avoid I2C contention and reduce ddcutil collisions.

### 6.3 Communication
- Web UI <-> Flask: WebSocket for live control + REST for CRUD
- Flask <-> Renderer: local WebSocket or Unix socket for state sync
- Flask <-> DDC: internal module with job queue; optionally separate worker process if needed

---

## 7. DDC/CI Requirements (Main Focus)

### 7.1 Capabilities Discovery
On startup and on demand:
- Enumerate connected displays and buses:
  - Use ddcutil detect (preferred)
  - Optionally parse /sys/class/drm/*/edid to map displays to connectors
- Determine supported VCP features and ranges:
  - ddcutil capabilities (if available and not too slow)
  - ddcutil getvcp 10 and getvcp 12 for required controls
- Store capabilities snapshot:
  - supported VCP codes
  - (current, max) values for each supported control
  - monitor identification (EDID vendor/model/serial if accessible)

Acceptance requirement: UI must show a clear status:
- "DDC Connected" / "DDC Not Available"
- Selected bus + display index
- Brightness supported? (Y/N)
- Contrast supported? (Y/N)
- Last error (if any)

### 7.2 Hardware Controls (Required)
- Brightness (VCP 0x10)
- Contrast (VCP 0x12)

Both must support:
- Read current value
- Set value
- Report max range and current
- Rate limiting / debouncing (see 7.5)

### 7.3 Additional VCP Controls (Best-Effort)
If reported as supported, expose in UI and profiles:
- Input source select (VCP 0x60) - optional, risky; default hidden
- Color preset / temperature modes - vendor-specific; only if discovered reliably
- RGB gains/cuts - only if present

These controls must be dynamically gated by capability detection.

### 7.4 Monitor Selection
Support 1..N displays if attached (optional), but must robustly support the common case:
- Single HDMI display

Selection rules:
- Default: first detected DDC-capable display
- If multiple:
  - Prefer HDMI connector that is primary output
  - Allow explicit configuration: DDC_DISPLAY_INDEX or DDC_BUS
- Expose selection in UI (admin-only) with "test set brightness to X" action.

### 7.5 Command Scheduling, Latency, and Safety
DDC is slow. Requirements:
- All DDC write operations go through a single queue to serialize I2C access.
- UI slider changes must be:
  - Client-side debounced to ~30-60Hz
  - Server-side coalesced: last write wins within a 50-100ms window
- Apply backpressure:
  - Do not allow unbounded queue growth
  - If overwhelmed, drop intermediate writes and apply only the latest value
- Timeouts and retries:
  - ddcutil calls time out (configurable, default 2s)
  - Retry on transient errors (configurable, default 1 retry)
- Observability:
  - Measure and report DDC command duration
  - Track last success timestamp

### 7.6 Permissions and Reliability
- Require i2c-dev module loaded at boot:
  - modprobe i2c-dev
- Avoid running everything as root:
  - Preferred: configure udev permissions for /dev/i2c-* or use a dedicated group
  - Alternate: restricted sudoers entry for ddcutil only (e.g., NOPASSWD: /usr/bin/ddcutil *)
- System must handle:
  - DDC/CI disabled (show actionable error)
  - No monitor found (show status; keep renderer running)

---

## 8. Renderer Requirements (Fullscreen Image)

### 8.1 Fullscreen Behavior
- Dedicated fullscreen window on HDMI
- No window decorations
- Keeps focus / stays on top where possible
- Recovers if display mode changes (hotplug)

### 8.2 Image Pipeline (Software)
Support:
- Scale modes: Fit (contain), Fill (cover), Stretch, 1:1, Custom scale
- Crop rectangle (normalized 0..1) + pan offsets
- Rotation: 0/90/180/270 (continuous optional)
- Background color for letterboxing
- Interpolation: nearest/linear/cubic

### 8.3 Pixel-Level Color (Software)
These are not a replacement for hardware brightness/contrast; they operate on pixels prior to display:
- brightness (offset)
- contrast (gain)
- saturation
- hue
- gamma
- optional temperature/tint

---

## 9. Profiles / Presets (Persistence)

### 9.1 Profile Contents (Must Include DDC)
A profile is an atomic set of:
- activeImageId
- DDC settings
  - brightness (0..max)
  - contrast (0..max)
  - plus any additional supported VCP values
- Render transform settings
- Software color settings
- Output settings

### 9.2 Profile Operations
- Create profile from current state
- Apply profile:
  - Applies DDC settings (serialized)
  - Applies renderer state (atomic)
- Rename, delete
- Mark default profile on boot

### 9.3 Persistence Semantics
- All state changes persist with debounce (250-500ms)
- On startup:
  - Load default profile if set, else last-used profile
  - Apply hardware DDC settings after DDC discovery
  - If DDC unavailable, apply renderer settings only and surface warning

---

## 10. Data Model (SQLite)

### 10.1 Tables

images
- id (ULID/UUID) PK
- original_name
- storage_path
- mime_type
- width, height
- size_bytes
- created_at

profiles
- id PK
- name UNIQUE
- data_json (full Profile object)
- is_default (bool)
- created_at, updated_at

app_state
- key PK (e.g., active_profile_id)
- value_json
- updated_at

ddc_cache
- id PK (singleton per display identity)
- display_identity_json (EDID fields)
- capabilities_json
- updated_at

---

## 11. State Schema

### 11.1 Runtime State (SystemState)

```
{
  "activeProfileId": "01H...",
  "activeImageId": "01H...",
  "ddc": {
    "status": "ok|degraded|unavailable",
    "display": { "index": 1, "bus": 3, "model": "...", "serial": "..." },
    "supported": { "brightness": true, "contrast": true, "vcp": ["0x10", "0x12"] },
    "values": { "brightness": { "cur": 40, "max": 100 }, "contrast": { "cur": 50, "max": 100 } },
    "lastError": null,
    "lastOkAt": "2026-01-29T00:00:00Z",
    "lastCommandMs": 120
  },
  "render": {
    "transform": {
      "mode": "fit|fill|stretch|one_to_one|custom",
      "scale": 1.0,
      "rotationDeg": 0,
      "flipH": false,
      "flipV": false,
      "crop": { "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0 },
      "pan": { "x": 0.0, "y": 0.0 }
    },
    "color": {
      "brightness": 0.0,
      "contrast": 1.0,
      "saturation": 1.0,
      "hue": 0.0,
      "gamma": 1.0,
      "temperature": 0.0,
      "tint": 0.0
    },
    "output": { "background": "#000000", "interpolation": "linear", "fullscreen": true }
  },
  "meta": { "version": 42, "updatedAt": "2026-01-29T00:00:00Z" }
}
```

### 11.2 Profile (Profile)

```
{
  "name": "Night",
  "activeImageId": "01H...",
  "ddc": { "brightness": 20, "contrast": 40, "extraVcp": {} },
  "render": { "transform": { "...": "..." }, "color": { "...": "..." }, "output": { "...": "..." } }
}
```

---

## 12. API Specification

### 12.1 REST

GET /api/health
- Returns:
  - server ok
  - renderer connected?
  - DDC status summary

GET /api/ddc/status
- Current DDC state, including bus/display selection and supported features

POST /api/ddc/rescan
- Re-run detect/capabilities and refresh cache

GET /api/ddc/values
- Returns current brightness/contrast and ranges

PATCH /api/ddc/values
- Payload:
  - { "brightness": 50 }, { "contrast": 60 }, or both
- Server:
  - validates supported + clamps to [0..max]
  - enqueues DDC write(s)
  - returns accepted + target version

GET /api/images
POST /api/images (upload multipart)
GET /api/images/{id}/thumb
DELETE /api/images/{id}

GET /api/state
- Full SystemState snapshot (authoritative)

PATCH /api/state
- Partial update for render settings and active image/profile

GET /api/profiles
POST /api/profiles
- Create profile from current state or provided JSON

POST /api/profiles/{id}/apply
- Apply profile atomically (DDC + renderer)

PATCH /api/profiles/{id}
DELETE /api/profiles/{id}
POST /api/profiles/{id}/default

### 12.2 WebSocket (/ws)
Used for live responsiveness.

Client -> Server messages:
- ddc.set { "brightness": 42 }
- ddc.set { "contrast": 55 }
- render.patch { "color": { "gamma": 1.1 } }
- profile.apply { "profileId": "..." }
- image.select { "imageId": "..." }

Server -> Clients broadcasts:
- state.snapshot { "state": SystemState }
- ddc.updated { "values": {...}, "meta": { "version": 43 } }
- ddc.error { "message": "...", "detail": "...", "recoverable": true }
- renderer.telemetry { "fps": 60, "frameMs": 8.4 }

---

## 13. DDC Implementation Details (Concrete Requirements)

### 13.1 Command Execution
Use ddcutil by default:
- Read:
  - ddcutil getvcp 10 --brief
  - ddcutil getvcp 12 --brief
- Write:
  - ddcutil setvcp 10 <value>
  - ddcutil setvcp 12 <value>
- Target selection:
  - --display <index> or --bus <busno> depending on detection results

Configuration knobs:
- DDCUTIL_PATH default /usr/bin/ddcutil
- DDC_TIMEOUT_MS default 2000
- DDC_RETRY_COUNT default 1
- DDC_TARGET (auto|display:index|bus:n)

### 13.2 Parsing and Validation
- Parse max/current from getvcp output.
- Clamp requested value to [0..max].
- If max is unknown, default clamp to [0..100] but mark as degraded.

### 13.3 Caching
Cache:
- capabilities and discovered max values
- last-known current values
Invalidate cache on:
- explicit rescan
- HDMI hotplug event (optional)
- repeated failures threshold (e.g., 3)

### 13.4 Failure Modes (Must Be Explicit)
- No displays detected
- I2C bus permission denied
- DDC/CI not supported
- VCP code unsupported
- Timeout / Device busy

UI must show:
- a short error
- a suggested remediation:
  - enable DDC/CI in monitor OSD
  - remove KVM/switch/adapter
  - run rescan
  - check permissions

---

## 14. "No Screen Sleep" Requirements

On service start:
- Disable DPMS and blanking depending on stack.

Minimum requirements:
- Document and support one operational mode:
  - X11: xset s off, xset -dpms, xset s noblank
- Provide installation instructions for console/KMS if used (kernel cmdline consoleblank=0).

Expose status in /api/health:
- whether sleep prevention commands were applied successfully
- last command output if failed

---

## 15. Security Requirements

- Default bind address: 127.0.0.1 (configurable)
- Optional auth:
  - token-based header X-Auth-Token
- Upload safety:
  - size limit (default 25MB)
  - verify file type via magic bytes
- CORS disabled by default

---

## 16. Deployment Requirements (systemd)

### 16.1 Services
- hdmi-control-web.service
- hdmi-control-render.service

Ordering:
- web starts first
- renderer starts after display target is ready

### 16.2 Service Hardening
- Restart=on-failure
- Logs to journald
- EnvironmentFile for configuration
- Optional ExecStartPre steps for:
  - modprobe i2c-dev
  - applying sleep-prevention commands

---

## 17. Testing and Acceptance

### 17.1 Automated Tests
- Unit: DDC parsing, clamping, job queue coalescing
- Integration: mock ddcutil output; verify API behavior under rapid updates
- Integration: profile apply triggers DDC writes then renderer sync

### 17.2 Manual Acceptance Criteria (Must Pass)
1) DDC Brightness
   - Slider change updates monitor hardware brightness within ~0.2-0.5s typical (DDC latency tolerant).
2) DDC Contrast
   - Slider change updates monitor hardware contrast similarly.
3) Capability gating
   - If contrast unsupported, UI disables it and shows reason.
4) Persistence
   - Reboot restores last/default profile including DDC brightness/contrast.
5) No sleep
   - Display remains on overnight (no blanking).
6) Robustness
   - Unplug/replug HDMI: system reports degraded/unavailable then recovers after rescan (or auto).

---

## 18. Implementation Milestones

1) DDC MVP
   - Detect display
   - Read/set brightness and contrast via API + WS
   - UI sliders + status view
2) Profiles
   - Save/apply profiles including DDC settings
3) Renderer MVP
   - Fullscreen image + upload + basic fit/fill/crop
4) Hardening
   - systemd, permissions, sleep prevention, monitoring/health
