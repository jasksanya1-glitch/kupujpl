"""Generate PNG/ICO favicons from static/favicon.svg."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("pip install pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "icons"
BRAND = "#0070d1"
BRAND_DARK = "#005fa8"
GOLD = "#fbbf24"
GOLD_LIGHT = "#fde68a"
WHITE = "#ffffff"
GREEN = "#22c55e"
INK = "#1a2230"


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _bg_color(x: int, y: int, size: int) -> tuple[int, int, int]:
    t = (x + y) / (2 * size)
    r1, g1, b1 = 0x0D, 0x8A, 0xE8
    r2, g2, b2 = 0x00, 0x5F, 0xA8
    return (_lerp(r1, r2, t), _lerp(g1, g2, t), _lerp(b1, b2, t))


def render_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    radius = size * 0.25
    for y in range(size):
        for x in range(size):
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            if dx < radius and dy < radius:
                corner_x = radius - dx if dx < radius else 0
                corner_y = radius - dy if dy < radius else 0
                if corner_x and corner_y and (corner_x**2 + corner_y**2) > radius**2:
                    continue
            elif dx < 0 or dy < 0:
                continue
            r, g, b = _bg_color(x, y, size)
            shine = max(0.0, 1.0 - (x + y) / (size * 1.1)) * 0.22
            px[x, y] = (
                min(255, int(r + 255 * shine)),
                min(255, int(g + 255 * shine)),
                min(255, int(b + 255 * shine)),
                255,
            )

    draw = ImageDraw.Draw(img)
    pad = size * 0.18
    body = [pad, size * 0.34, size - pad, size * 0.72]
    draw.rounded_rectangle(body, radius=size * 0.14, fill=WHITE)

    dpad = [size * 0.28, size * 0.44, size * 0.42, size * 0.58]
    draw.rounded_rectangle(dpad, radius=size * 0.03, fill=BRAND)

    btn_r = size * 0.045
    draw.ellipse(
        (size * 0.58 - btn_r, size * 0.45 - btn_r, size * 0.58 + btn_r, size * 0.45 + btn_r),
        fill=GREEN,
    )
    draw.ellipse(
        (size * 0.68 - btn_r, size * 0.51 - btn_r, size * 0.68 + btn_r, size * 0.51 + btn_r),
        fill=BRAND,
    )

    tag_cx, tag_cy = size * 0.76, size * 0.24
    tag_r = size * 0.13
    draw.ellipse((tag_cx - tag_r, tag_cy - tag_r, tag_cx + tag_r, tag_cy + tag_r), fill=GOLD)
    inner = tag_r * 0.76
    draw.ellipse((tag_cx - inner, tag_cy - inner, tag_cx + inner, tag_cy + inner), fill=GOLD_LIGHT)

    try:
        from PIL import ImageFont

        font = ImageFont.truetype("arialbd.ttf", max(8, int(size * 0.16)))
    except Exception:
        font = ImageFont.load_default()
    text = "zł"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((tag_cx - tw / 2, tag_cy - th / 2 - size * 0.01), text, fill=INK, font=font)
    return img


def write_ico(path: Path, images: list[Image.Image]) -> None:
    entries = []
    for im in images:
        rgba = im.convert("RGBA")
        w, h = rgba.size
        raw = rgba.tobytes()
        entries.append((w, h, raw))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dir_parts = []
    data_parts = []
    for w, h, raw in entries:
        dir_parts.append(
            struct.pack(
                "<BBBBHHII",
                w if w < 256 else 0,
                h if h < 256 else 0,
                0,
                0,
                1,
                32,
                len(raw),
                offset,
            )
        )
        data_parts.append(raw)
        offset += len(raw)

    bmp_header = struct.pack("<IIIHHIIIIII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    # ICO stores BMP with flipped height — use PNG-in-ICO instead (simpler via Pillow)
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(path, format="ICO", sizes=[(im.width, im.height) for im in images])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 180, 192, 512]
    rendered = {s: render_icon(s) for s in sizes}
    rendered[16].save(OUT / "favicon-16.png")
    rendered[32].save(OUT / "favicon-32.png")
    rendered[180].save(OUT / "apple-touch-icon.png")
    rendered[192].save(OUT / "icon-192.png")
    rendered[512].save(OUT / "icon-512.png")
    write_ico(ROOT / "app" / "static" / "favicon.ico", [rendered[16], rendered[32], rendered[48]])
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
