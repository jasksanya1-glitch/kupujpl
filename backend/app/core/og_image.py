"""Dynamic Open Graph card generator for game pages.

Renders a 1200x630 branded card (cover + title + price) and caches it on disk.
Falls back gracefully if Pillow or the remote cover is unavailable.
"""
from __future__ import annotations

import hashlib
import io
import time
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "og_cache"
CACHE_TTL_SECONDS = 12 * 3600

W, H = 1200, 630
BG = (6, 16, 36)
PANEL = (10, 24, 48)
ACCENT = (255, 230, 0)
TEXT = (233, 240, 251)
MUTED = (150, 170, 194)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/{name}.ttf",
    "/usr/share/fonts/truetype/liberation/{name}.ttf",
]
_FONT_MAP = {
    "bold": ["DejaVuSans-Bold", "LiberationSans-Bold"],
    "regular": ["DejaVuSans", "LiberationSans-Regular"],
}


def _load_font(kind: str, size: int):
    from PIL import ImageFont

    for name in _FONT_MAP[kind]:
        for tmpl in _FONT_CANDIDATES:
            path = tmpl.format(name=name)
            if Path(path).is_file():
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default()


def _fetch_cover(url: str):
    from PIL import Image

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KupujPL-OG"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = resp.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and (draw.textlength(lines[-1], font=font) > max_width):
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def _cache_key(slug: str, title: str, price_text: str, cover_url: str) -> str:
    raw = f"{slug}|{title}|{price_text}|{cover_url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def render_logo_png() -> bytes | None:
    """Square branded logo (512x512) for Organization schema / social."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "logo.png"
    if cache_file.is_file():
        try:
            return cache_file.read_bytes()
        except OSError:
            pass
    try:
        size = 512
        img = Image.new("RGB", (size, size), BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size, 16], fill=ACCENT)
        draw.rectangle([0, size - 16, size, size], fill=ACCENT)
        f_brand = _load_font("bold", 96)
        f_sub = _load_font("bold", 52)
        draw.text((size / 2, 200), "KupujPL", font=f_brand, fill=TEXT, anchor="mm")
        draw.text((size / 2, 300), "GRY", font=f_sub, fill=ACCENT, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        try:
            cache_file.write_bytes(data)
        except OSError:
            pass
        return data
    except Exception:
        return None


def render_og_png(slug: str, title: str, price_text: str, cover_url: str | None) -> bytes | None:
    """Return PNG bytes for the game OG card, or None if rendering is impossible."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(slug, title, price_text, cover_url or "")
    cache_file = CACHE_DIR / f"{key}.png"
    if cache_file.is_file() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SECONDS:
        try:
            return cache_file.read_bytes()
        except OSError:
            pass

    try:
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        # accent top bar
        draw.rectangle([0, 0, W, 10], fill=ACCENT)

        # cover panel (left)
        panel_x0, panel_y0, panel_x1, panel_y1 = 60, 70, 470, 560
        draw.rectangle([panel_x0, panel_y0, panel_x1, panel_y1], fill=PANEL)
        if cover_url:
            try:
                cover = _fetch_cover(cover_url)
                box_w, box_h = panel_x1 - panel_x0 - 20, panel_y1 - panel_y0 - 20
                cw, ch = cover.size
                scale = min(box_w / cw, box_h / ch)
                nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
                cover = cover.resize((nw, nh))
                ox = panel_x0 + 10 + (box_w - nw) // 2
                oy = panel_y0 + 10 + (box_h - nh) // 2
                img.paste(cover, (ox, oy))
            except Exception:
                pass

        # right text column
        tx = 510
        f_kicker = _load_font("bold", 30)
        f_title = _load_font("bold", 60)
        f_price = _load_font("bold", 52)
        f_foot = _load_font("regular", 28)

        draw.text((tx, 78), "KUPUJPL // GRY", font=f_kicker, fill=ACCENT)

        title_lines = _wrap(draw, title, f_title, W - tx - 60, max_lines=3)
        y = 150
        for line in title_lines:
            draw.text((tx, y), line, font=f_title, fill=TEXT)
            y += 72

        y = max(y + 10, 360)
        if price_text:
            draw.text((tx, y), price_text, font=f_price, fill=ACCENT)

        draw.text((tx, 540), "kupujpl.pl/games · porównywarka cen gier PC", font=f_foot, fill=MUTED)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        try:
            cache_file.write_bytes(data)
        except OSError:
            pass
        return data
    except Exception:
        return None
