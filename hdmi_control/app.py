from __future__ import annotations
import json
import os
from threading import Lock
from flask import Flask, jsonify, request, send_file, render_template
from io import BytesIO
from PIL import Image
from pathlib import Path
from flask_socketio import SocketIO, emit

from .config import CONFIG
from .db import init_db
from .state import SystemState
from .ddc.controller import DdcController
from .ddc.ddcutil import DdcUtil
from .sleep import apply_sleep_prevention
from .images import add_image, list_images, delete_image, get_image_path
from .profiles import list_profiles, create_profile, update_profile, delete_profile as delete_profile_db, set_default_profile, get_profile, load_default_or_last
from .app_state import get_state_value, set_state_value
from .drm import list_connectors


socketio = SocketIO(async_mode="threading", cors_allowed_origins=[])
state_lock = Lock()
state = SystemState()


ddc_controller = DdcController(state.ddc, lambda: state.bump(), state_lock)


def create_app() -> Flask:
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.config["MAX_CONTENT_LENGTH"] = CONFIG.upload_max_mb * 1024 * 1024

    init_db()
    os.makedirs(CONFIG.data_dir, exist_ok=True)

    ddc_controller.start()
    ddc_controller.rescan()
    ddc_controller.wake_display()

    if CONFIG.disable_dpms:
        app.sleep_status = apply_sleep_prevention()
    else:
        app.sleep_status = None

    active_profile = get_state_value("active_profile_id")
    if active_profile and "value" in active_profile:
        state.activeProfileId = active_profile["value"]
    else:
        state.activeProfileId = load_default_or_last()

    selected_output = get_state_value("ddc_output")
    if selected_output and "value" in selected_output:
        pref = selected_output["value"]
        ddc_controller.set_preference(pref.get("connector"), pref.get("bus"), pref.get("display_index"))

    socketio.init_app(app)
    ddc_controller.set_on_update(lambda: _ddc_updated())

    @app.before_request
    def auth_guard():
        if CONFIG.auth_token and request.path.startswith("/api/"):
            token = request.headers.get("X-Auth-Token")
            if token != CONFIG.auth_token:
                return jsonify({"error": "unauthorized"}), 401

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/health")
    def health():
        return jsonify({
            "ok": True,
            "renderer": {"connected": True},
            "ddc": state.ddc.__dict__,
            "sleep_prevention": {
                "ok": app.sleep_status.ok if app.sleep_status else False,
                "output": app.sleep_status.output if app.sleep_status else None,
            },
        })

    @app.route("/api/ddc/status")
    def ddc_status():
        return jsonify(state.ddc.__dict__)

    @app.route("/api/ddc/outputs")
    def ddc_outputs():
        return jsonify({
            "connectors": list_connectors(),
            "ddc_displays": state.ddc.display,
            "preference": ddc_controller.get_preference(),
        })

    @app.route("/api/ddc/select", methods=["POST"])
    def ddc_select():
        payload = request.get_json(force=True)
        connector = payload.get("connector")
        bus = payload.get("bus")
        display_index = payload.get("display_index")
        ddc_controller.set_preference(connector, bus, display_index)
        set_state_value("ddc_output", {"value": {"connector": connector, "bus": bus, "display_index": display_index}})
        ddc_controller.rescan()
        ddc_controller.wake_display()
        return jsonify({"ok": True, "ddc": state.ddc.__dict__})

    @app.route("/api/ddc/rescan", methods=["POST"])
    def ddc_rescan():
        ddc_controller.rescan()
        ddc_controller.wake_display()
        return jsonify({"ok": True, "ddc": state.ddc.__dict__})

    @app.route("/api/ddc/values")
    def ddc_values():
        return jsonify(state.ddc.values)

    @app.route("/api/ddc/debug")
    def ddc_debug():
        util = DdcUtil()
        target_args = ddc_controller.get_target_args()
        return jsonify({
            "display": state.ddc.display,
            "target_args": target_args,
            "detect": util.run_raw(["detect", "--brief"]),
            "capabilities": util.run_raw(["capabilities"] + target_args, timeout_ms=CONFIG.ddc_timeout_ms * 2),
            "getvcp_10": util.run_raw(["getvcp", "10", "--brief"] + target_args),
            "getvcp_12": util.run_raw(["getvcp", "12", "--brief"] + target_args),
            "getvcp_D6": util.run_raw(["getvcp", "D6", "--brief"] + target_args),
            "getvcp_60": util.run_raw(["getvcp", "60", "--brief"] + target_args),
        })

    @app.route("/api/ddc/wake", methods=["POST"])
    def ddc_wake():
        ddc_controller.wake_display()
        return jsonify({"ok": True})

    @app.route("/api/ddc/values", methods=["PATCH"])
    def ddc_set_values():
        payload = request.get_json(force=True)
        if "brightness" in payload:
            ddc_controller.set_brightness(payload["brightness"])
        if "contrast" in payload:
            ddc_controller.set_contrast(payload["contrast"])
        return jsonify({"accepted": True, "version": state.meta["version"]})

    @app.route("/api/images", methods=["GET"])
    def images_list():
        return jsonify(_sanitize_images(list_images()))

    @app.route("/api/images", methods=["POST"])
    def images_upload():
        if "file" not in request.files:
            return jsonify({"error": "file missing"}), 400
        image = add_image(request.files["file"])
        return jsonify(_sanitize_images([image])[0])

    @app.route("/api/images/<image_id>", methods=["DELETE"])
    def images_delete(image_id: str):
        delete_image(image_id)
        if state.activeImageId == image_id:
            state.activeImageId = None
            state.bump()
        return jsonify({"ok": True})

    @app.route("/api/images/<image_id>/thumb")
    def images_thumb(image_id: str):
        path = get_image_path(image_id)
        if not path or not os.path.exists(path):
            return jsonify({"error": "not found"}), 404
        with Image.open(path) as image:
            image.thumbnail((256, 256))
            buf = BytesIO()
            image.save(buf, format="JPEG")
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")

    @app.route("/api/images/<image_id>/file")
    def images_file(image_id: str):
        path = get_image_path(image_id)
        if not path or not os.path.exists(path):
            return jsonify({"error": "not found"}), 404
        return send_file(path)

    @app.route("/api/state")
    def get_state():
        with state_lock:
            return jsonify(state.to_dict())

    @app.route("/api/state", methods=["PATCH"])
    def patch_state():
        payload = request.get_json(force=True)
        with state_lock:
            if "render" in payload:
                for key, value in payload["render"].items():
                    if hasattr(state.render, key):
                        current = getattr(state.render, key)
                        if isinstance(current, dict) and isinstance(value, dict):
                            current.update(value)
                        else:
                            setattr(state.render, key, value)
            if "activeImageId" in payload:
                state.activeImageId = payload["activeImageId"]
            state.bump()
            _persist_state()
            socketio.emit("state.snapshot", {"state": state.to_dict()})
        return jsonify(state.to_dict())

    @app.route("/api/profiles", methods=["GET"])
    def profiles_list():
        return jsonify(list_profiles())

    @app.route("/api/profiles", methods=["POST"])
    def profiles_create():
        payload = request.get_json(force=True)
        name = payload.get("name") or "Profile"
        data = payload.get("data") or _profile_from_state()
        profile = create_profile(name, data)
        return jsonify(profile)

    @app.route("/api/profiles/<profile_id>", methods=["PATCH"])
    def profiles_patch(profile_id: str):
        payload = request.get_json(force=True)
        update_profile(profile_id, payload.get("name"), payload.get("data"))
        return jsonify({"ok": True})

    @app.route("/api/profiles/<profile_id>", methods=["DELETE"])
    def profiles_delete(profile_id: str):
        delete_profile_db(profile_id)
        return jsonify({"ok": True})

    @app.route("/api/profiles/<profile_id>/default", methods=["POST"])
    def profiles_default(profile_id: str):
        set_default_profile(profile_id)
        return jsonify({"ok": True})

    @app.route("/api/profiles/<profile_id>/apply", methods=["POST"])
    def profiles_apply(profile_id: str):
        profile = get_profile(profile_id)
        if not profile:
            return jsonify({"error": "not found"}), 404
        _apply_profile(profile["data"], profile_id)
        return jsonify({"ok": True})

    @socketio.on("connect")
    def ws_connect():
        emit("state.snapshot", {"state": state.to_dict()})

    @socketio.on("ddc.set")
    def ws_ddc_set(message):
        if "brightness" in message:
            ddc_controller.set_brightness(message["brightness"])
        if "contrast" in message:
            ddc_controller.set_contrast(message["contrast"])
        emit("ddc.updated", {"values": state.ddc.values, "meta": state.meta}, broadcast=True)

    @socketio.on("render.patch")
    def ws_render_patch(message):
        with state_lock:
            for section in ("transform", "color", "output"):
                if section in message:
                    current = getattr(state.render, section)
                    if isinstance(current, dict):
                        current.update(message[section])
                    else:
                        setattr(state.render, section, message[section])
            state.bump()
            _persist_state()
            emit("state.snapshot", {"state": state.to_dict()}, broadcast=True)

    @socketio.on("image.select")
    def ws_image_select(message):
        with state_lock:
            state.activeImageId = message.get("imageId")
            state.bump()
            _persist_state()
            emit("state.snapshot", {"state": state.to_dict()}, broadcast=True)

    @socketio.on("profile.apply")
    def ws_profile_apply(message):
        profile_id = message.get("profileId")
        profile = get_profile(profile_id) if profile_id else None
        if not profile:
            emit("ddc.error", {"message": "Profile not found", "detail": "", "recoverable": True})
            return
        _apply_profile(profile["data"], profile_id)
        emit("state.snapshot", {"state": state.to_dict()}, broadcast=True)

    return app


def _profile_from_state() -> dict:
    return {
        "name": "",
        "activeImageId": state.activeImageId,
        "ddc": {
            "brightness": state.ddc.values["brightness"].get("cur"),
            "contrast": state.ddc.values["contrast"].get("cur"),
            "extraVcp": {},
        },
        "render": {
            "transform": state.render.transform,
            "color": state.render.color,
            "output": state.render.output,
        },
    }


def _apply_profile(profile_data: dict, profile_id: str | None) -> None:
    ddc = profile_data.get("ddc", {})
    if "brightness" in ddc and ddc["brightness"] is not None:
        ddc_controller.set_brightness(ddc["brightness"])
    if "contrast" in ddc and ddc["contrast"] is not None:
        ddc_controller.set_contrast(ddc["contrast"])
    render = profile_data.get("render", {})
    for section in ("transform", "color", "output"):
        if section in render:
            current = getattr(state.render, section)
            if isinstance(current, dict):
                current.update(render[section])
            else:
                setattr(state.render, section, render[section])
    state.activeImageId = profile_data.get("activeImageId")
    state.activeProfileId = profile_id
    state.bump()
    _persist_state()


def _persist_state() -> None:
    if state.activeProfileId:
        set_state_value("active_profile_id", {"value": state.activeProfileId})


def _ddc_updated() -> None:
    with state_lock:
        state.bump()
    try:
        socketio.emit("ddc.updated", {"values": state.ddc.values, "meta": state.meta})
    except Exception:
        pass


def _sanitize_images(images: list[dict]) -> list[dict]:
    sanitized = []
    for image in images:
        copy = dict(image)
        copy.pop("storage_path", None)
        sanitized.append(copy)
    return sanitized


if __name__ == "__main__":
    app = create_app()
    socketio.run(app, host=CONFIG.bind_host, port=CONFIG.bind_port, allow_unsafe_werkzeug=True)

