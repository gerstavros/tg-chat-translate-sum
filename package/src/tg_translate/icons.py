"""
Icons module — programmatic icon generation for Chat Translate & Sum for Telegram.

Each icon is a small PNG rendered via Pillow, cached as CTkImage.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

import customtkinter as ctk

_ICON_CACHE: dict[str, ctk.CTkImage] = {}
_ICONS_DIR = Path(__file__).parent / "assets"



def _load_svg(name: str, size=24) -> ctk.CTkImage | None:
    """Load an SVG file from assets directory, render to CTkImage."""
    svg_path = _ICONS_DIR / f"{name}.svg"
    if not svg_path.exists():
        return None

    try:
        # Try cairosvg first
        import cairosvg
        import io
        png_data = cairosvg.svg2png(url=str(svg_path), output_width=size, output_height=size)
        img = Image.open(io.BytesIO(png_data))
        img = img.convert("RGBA") if img.mode != "RGBA" else img
        ctk_img = ctk.CTkImage(img, size=(size, size))
        _ICON_CACHE[name] = ctk_img
        return ctk_img
    except ImportError:
        pass
    except Exception:
        pass

    try:
        # Try rsvg-convert CLI
        import subprocess
        import io
        result = subprocess.run(
            ["rsvg-convert", str(svg_path), "-w", str(size), "-h", str(size), "-f", "png"],
            capture_output=True,
        )
        if result.returncode == 0:
            img = Image.open(io.BytesIO(result.stdout))
            img = img.convert("RGBA") if img.mode != "RGBA" else img
            ctk_img = ctk.CTkImage(img, size=(size, size))
            _ICON_CACHE[name] = ctk_img
            return ctk_img
    except (FileNotFoundError, Exception):
        pass

    return None

def _make_icon(name: str, draw_func, size=24) -> ctk.CTkImage | None:
    if name in _ICON_CACHE:
        return _ICON_CACHE[name]
    if Image is None:
        return None

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_func(draw, size)
    ctk_img = ctk.CTkImage(img, size=(size, size))
    _ICON_CACHE[name] = ctk_img
    return ctk_img


def _chat_draw(d, s):
    d.rounded_rectangle([3, 6, s-3, s-8], radius=4, fill="#FFFFFF")
    d.polygon([s-12, s-8, s-8, s-2, s-6, s-8], fill="#FFFFFF")


def _group_draw(d, s):
    d.ellipse([5, 3, s-5, s//2-2], fill="#FFFFFF")
    d.ellipse([s//2+2, 5, s-4, s//2], fill="#FFFFFF")
    d.polygon([4, s-3, s//2-2, s-3, s//2-2, s//2+4, 4, s//2+4], fill="#FFFFFF")
    d.polygon([s//2+1, s-3, s-3, s-3, s-3, s//2+5, s//2+1, s//2+5], fill="#FFFFFF")


def _channel_draw(d, s):
    d.polygon([5, 10, s-8, 4, s-8, s-6, 5, s-10], fill="#FFFFFF")
    d.ellipse([s-10, s//2-3, s-2, s//2+3], fill="#FFFFFF")


def _photo_draw(d, s):
    d.rectangle([3, 6, s-3, s-4], outline="#FFFFFF", width=2)
    d.ellipse([s//2-5, s//2-4, s//2+5, s//2+6], outline="#FFFFFF", width=2)
    d.rectangle([s-10, 6, s-4, 11], fill="#FFFFFF")


def _video_draw(d, s):
    d.rectangle([2, 6, s-8, s-5], outline="#FFFFFF", width=2)
    d.polygon([s-8, s//2-5, s-3, s//2-8, s-3, s//2+7, s-8, s//2+4], fill="#FFFFFF")


def _voice_draw(d, s):
    d.rectangle([s//2-3, 2, s//2+3, s//2+2], fill="#FFFFFF")
    d.arc([s//2-7, s//2-3, s//2+7, s//2+10], 180, 0, fill="#FFFFFF", width=2)
    d.rectangle([s//2-5, s//2+6, s//2+5, s-4], fill="#FFFFFF")


def _sticker_draw(d, s):
    d.rectangle([3, 3, s-3, s-3], outline="#FFFFFF", width=2, radius=4)
    d.polygon([s//2-6, s//2-2, s//2, s//2+4, s//2+6, s//2-2], fill="#FFFFFF")


def _document_draw(d, s):
    d.polygon([5, 3, s-6, 3, s-3, 6, s-3, s-3, 5, s-3], fill="#FFFFFF")
    d.line([8, s//2-2, s-8, s//2-2], fill="#AAAAAA", width=2)
    d.line([8, s//2+3, s-8, s//2+3], fill="#AAAAAA", width=2)


def _settings_draw(d, s):
    c = s // 2
    d.ellipse([c-6, c-6, c+6, c+6], outline="#FFFFFF", width=2)
    d.ellipse([c-3, c-3, c+3, c+3], fill="#FFFFFF")
    for angle in [0, 45, 90, 135]:
        import math
        rad = math.radians(angle)
        dx, dy = int(9 * math.cos(rad)), int(9 * math.sin(rad))
        d.line([c, c, c+dx, c+dy], fill="#FFFFFF", width=2)


def _translate_draw(d, s):
    d.ellipse([3, 3, s-3, s-3], outline="#FFFFFF", width=2)
    d.line([3, s//2, s-3, s//2], fill="#FFFFFF", width=2)
    d.line([s//2, 3, s//2, s-3], fill="#FFFFFF", width=2)
    d.arc([s//2-8, s//2-5, s//2+8, s//2+5], 180, 0, fill="#FFFFFF", width=2)


def _refresh_draw(d, s):
    d.arc([4, 4, s-4, s-4], 225, 405, fill="#FFFFFF", width=2)
    d.polygon([s-4, s//2-3, s-8, s//2-8, s-8, s//2+2], fill="#FFFFFF")


def _copy_draw(d, s):
    d.rectangle([7, 5, s-4, s-5], outline="#FFFFFF", width=2)
    d.rectangle([4, 8, s-7, s-2], outline="#FFFFFF", width=2)


def _read_draw(d, s):
    d.line([4, s//2+1, s//2-3, s-4], fill="#3DB0E3", width=3)
    d.line([s//2-3, s-4, s-4, 5], fill="#3DB0E3", width=3)


def _close_draw(d, s):
    d.line([4, 4, s-4, s-4], fill="#FFFFFF", width=2)
    d.line([s-4, 4, 4, s-4], fill="#FFFFFF", width=2)


def _link_draw(d, s):
    d.arc([3, s//2-7, s-10, s//2+7], 300, 120, fill="#3DB0E3", width=2)
    d.arc([s-18, s//2-10, s-3, s//2+10], 120, 300, fill="#3DB0E3", width=2)


# list of available icons
_ICONS = {
    "chat": _chat_draw,
    "group": _group_draw,
    "channel": _channel_draw,
    "photo": _photo_draw,
    "video": _video_draw,
    "voice": _voice_draw,
    "sticker": _sticker_draw,
    "document": _document_draw,
    "settings": _settings_draw,
    "translate": _translate_draw,
    "refresh": _refresh_draw,
    "copy": _copy_draw,
    "read": _read_draw,
    "close": _close_draw,
    "link": _link_draw,
}


def get(name: str, size=24) -> ctk.CTkImage | None:
    # Try SVG file first
    svg_icon = _load_svg(name, size)
    if svg_icon is not None:
        return svg_icon
    # Fall back to programmatic draw
    draw_func = _ICONS.get(name)
    if draw_func is None:
        return None
    return _make_icon(name, draw_func, size)
