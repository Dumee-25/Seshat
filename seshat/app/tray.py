"""System-tray icon for the desktop app.

Thin GUI glue over pystray + Pillow, driven by a controller object (the
DesktopApp) that exposes the actions and status. Not exercised in CI (no
display); the behaviour it drives lives in supervisor.py / server.py.
"""

from __future__ import annotations

import math
from typing import Protocol

STAR_GOLD = (201, 162, 39, 255)  # #C9A227, the Seshat accent


class TrayController(Protocol):
    def open_window(self) -> None: ...
    def status_label(self) -> str: ...
    def is_paused(self) -> bool: ...
    def toggle_pause(self) -> None: ...
    def quit(self) -> None: ...


def make_star_image(size: int = 64):
    """The seven-pointed Seshat star (her emblem) as a tray icon."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx = cy = size / 2
    radius = size * 0.42
    for i in range(7):
        angle = -math.pi / 2 + i * (2 * math.pi / 7)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        draw.line((cx, cy, x, y), fill=STAR_GOLD, width=max(2, size // 24))
    dot = size * 0.06
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=STAR_GOLD)
    return image


def build_icon(controller: TrayController):
    import pystray
    from pystray import Menu, MenuItem

    menu = Menu(
        MenuItem("Open Seshat", lambda icon, item: controller.open_window(), default=True),
        MenuItem(lambda item: controller.status_label(), None, enabled=False),
        MenuItem(
            lambda item: "Resume watching" if controller.is_paused() else "Pause watching",
            lambda icon, item: controller.toggle_pause(),
        ),
        Menu.SEPARATOR,
        MenuItem("Quit Seshat", lambda icon, item: controller.quit()),
    )
    return pystray.Icon("seshat", make_star_image(), "Seshat", menu)
