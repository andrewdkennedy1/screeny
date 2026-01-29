import io
import json
import os
import threading
import time
from dataclasses import dataclass

try:
    import pygame
except Exception:
    pygame = None

import socketio
from PIL import Image, ImageEnhance, ImageOps


@dataclass
class RendererConfig:
    server_url: str = os.getenv("SERVER_URL", "http://127.0.0.1:5000")
    poll_interval: float = float(os.getenv("POLL_INTERVAL", "1.0"))


def fetch_json(url: str) -> dict:
    import urllib.request
    with urllib.request.urlopen(url, timeout=2) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_image_url(server_url: str, image_id: str) -> str | None:
    data = fetch_json(f"{server_url}/api/images")
    for item in data:
        if item["id"] == image_id:
            return f"{server_url}/api/images/{image_id}/file"
    return None


def fetch_image_bytes(url: str) -> bytes | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.read()
    except Exception:
        return None


def apply_color(image: Image.Image, color: dict) -> Image.Image:
    brightness = float(color.get("brightness", 0.0))
    contrast = float(color.get("contrast", 1.0))
    saturation = float(color.get("saturation", 1.0))
    gamma = float(color.get("gamma", 1.0))
    temperature = float(color.get("temperature", 0.0))
    tint = float(color.get("tint", 0.0))

    if brightness != 0.0:
        image = ImageEnhance.Brightness(image).enhance(1.0 + brightness)
    if contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast)
    if saturation != 1.0:
        image = ImageEnhance.Color(image).enhance(saturation)

    if gamma != 1.0:
        inv = 1.0 / max(gamma, 0.01)
        image = image.point(lambda p: int(255 * ((p / 255) ** inv)))

    if temperature != 0.0 or tint != 0.0:
        r, g, b = image.split()
        r = r.point(lambda p: max(0, min(255, int(p + temperature * 10))))
        b = b.point(lambda p: max(0, min(255, int(p - temperature * 10))))
        g = g.point(lambda p: max(0, min(255, int(p + tint * 10))))
        image = Image.merge("RGB", (r, g, b))

    return image


def apply_transform(image: Image.Image, transform: dict, screen_size: tuple[int, int], interpolation: str) -> Image.Image:
    crop = transform.get("crop", {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
    if crop:
        x = max(0.0, min(1.0, float(crop.get("x", 0.0))))
        y = max(0.0, min(1.0, float(crop.get("y", 0.0))))
        w = max(0.01, min(1.0, float(crop.get("w", 1.0))))
        h = max(0.01, min(1.0, float(crop.get("h", 1.0))))
        img_w, img_h = image.size
        left = int(img_w * x)
        upper = int(img_h * y)
        right = int(img_w * (x + w))
        lower = int(img_h * (y + h))
        image = image.crop((left, upper, right, lower))

    rotation = int(transform.get("rotationDeg", 0))
    if rotation:
        image = image.rotate(rotation, expand=True)

    if transform.get("flipH"):
        image = ImageOps.mirror(image)
    if transform.get("flipV"):
        image = ImageOps.flip(image)

    mode = transform.get("mode", "fit")
    scale = float(transform.get("scale", 1.0))
    screen_w, screen_h = screen_size
    img_w, img_h = image.size

    if interpolation == "nearest":
        resample = Image.NEAREST
    elif interpolation == "cubic":
        resample = Image.BICUBIC
    else:
        resample = Image.BILINEAR

    if mode == "stretch":
        return image.resize((screen_w, screen_h), resample=resample)

    if mode == "one_to_one":
        return image

    if mode == "custom":
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        return image.resize((max(1, new_w), max(1, new_h)), resample=resample)

    if mode == "fill":
        factor = max(screen_w / img_w, screen_h / img_h)
    else:
        factor = min(screen_w / img_w, screen_h / img_h)
    new_w = int(img_w * factor)
    new_h = int(img_h * factor)
    return image.resize((max(1, new_w), max(1, new_h)), resample=resample)


class StateFeed:
    def __init__(self, server_url: str):
        self.server_url = server_url
        self.state = {}
        self.lock = threading.Lock()
        self.connected = False
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self.sio.on("state.snapshot", self._on_snapshot)
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)

    def start(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        while True:
            try:
                self.sio.connect(self.server_url)
                self.sio.wait()
            except Exception:
                time.sleep(1.0)

    def _on_connect(self):
        self.connected = True

    def _on_disconnect(self):
        self.connected = False

    def _on_snapshot(self, payload):
        with self.lock:
            self.state = payload.get("state", {})

    def get_state(self) -> dict:
        with self.lock:
            return dict(self.state)


def render_loop(config: RendererConfig) -> None:
    feed = StateFeed(config.server_url)
    feed.start()

    if pygame is None:
        print("pygame not installed; running headless renderer")
        while True:
            time.sleep(config.poll_interval)
        return

    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Screeny Renderer")
    clock = pygame.time.Clock()

    image_id = None
    image_url = None
    image_bytes = None

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return

        state = feed.get_state()
        if not state:
            time.sleep(0.1)
            continue

        new_image_id = state.get("activeImageId")
        if new_image_id != image_id:
            image_id = new_image_id
            if image_id:
                image_url = resolve_image_url(config.server_url, image_id)
                image_bytes = fetch_image_bytes(image_url) if image_url else None
            else:
                image_url = None
                image_bytes = None

        screen.fill((0, 0, 0))
        if image_bytes:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            render = state.get("render", {})
            transform = render.get("transform", {})
            color = render.get("color", {})
            output = render.get("output", {})
            interpolation = output.get("interpolation", "linear")
            bg = output.get("background", "#000000")
            if bg.startswith("#") and len(bg) == 7:
                screen.fill(tuple(int(bg[i:i+2], 16) for i in (1, 3, 5)))
            image = apply_color(image, color)
            image = apply_transform(image, transform, screen.get_size(), interpolation)
            mode = image.mode
            data = image.tobytes()
            surface = pygame.image.frombuffer(data, image.size, mode)
            x = (screen.get_width() - surface.get_width()) // 2
            y = (screen.get_height() - surface.get_height()) // 2
            screen.blit(surface, (x, y))

        pygame.display.flip()
        clock.tick(30)
        time.sleep(config.poll_interval)


if __name__ == "__main__":
    render_loop(RendererConfig())
