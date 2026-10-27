"""生成测试样片：覆盖带 GPS / 无 GPS / 竖拍 / 无 EXIF / HEIC 几种情况。

只在开发验证时用，不参与打包。
运行：python tools/make_samples.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import piexif
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "in"

SKY_TOP = (150, 196, 232)
SKY_BOTTOM = (228, 238, 244)
FAR = (150, 176, 198)
NEAR = (104, 134, 160)
WATER_TOP = (92, 126, 154)
WATER_BOTTOM = (54, 82, 108)


def make_scene(w: int, h: int, warm: bool = False) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    horizon = int(h * 0.62)
    for y in range(horizon):
        t = y / max(1, horizon - 1)
        color = tuple(int(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)

    sun_r = int(min(w, h) * 0.045)
    draw.ellipse([int(w * 0.72) - sun_r, int(horizon * 0.34) - sun_r,
                  int(w * 0.72) + sun_r, int(horizon * 0.34) + sun_r],
                 fill=(255, 226, 160) if warm else (252, 238, 196))

    for peak, color, base in ((0.30, FAR, horizon), (0.55, NEAR, horizon)):
        pts = [(0, base)]
        for i in range(0, 101, 2):
            x = w * i / 100
            y = horizon - math.sin(i * math.pi / 55) * h * peak * 0.42 - h * 0.04
            pts.append((x, y))
        pts.append((w, base))
        draw.polygon(pts, fill=color)

    for y in range(horizon, h):
        t = (y - horizon) / max(1, h - horizon - 1)
        color = tuple(int(WATER_TOP[i] + (WATER_BOTTOM[i] - WATER_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)

    for i in range(6):
        y = horizon + int(h * (0.06 + i * 0.05))
        pad = int(w * (0.08 + i * 0.03))
        draw.line([(pad, y), (w - pad, y)], fill=(120, 152, 176), width=max(1, h // 400))
    return img


def exif_bytes(taken: str, gps: tuple[float, float] | None, orientation: int = 1,
               make: str = "", model: str = "") -> bytes:
    zeroth = {piexif.ImageIFD.Orientation: orientation}
    if make:
        zeroth[piexif.ImageIFD.Make] = make
    if model:
        zeroth[piexif.ImageIFD.Model] = model
    exif = {
        piexif.ExifIFD.DateTimeOriginal: taken,
        piexif.ExifIFD.DateTimeDigitized: taken,
    }
    gps_ifd = {}
    if gps is not None:
        lat, lon = gps

        def to_dms(value: float):
            value = abs(value)
            deg = int(value)
            minute = int((value - deg) * 60)
            sec = round((value - deg - minute / 60) * 3600 * 100)
            return ((deg, 1), (minute, 1), (sec, 100))

        gps_ifd = {
            piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: to_dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: to_dms(lon),
        }
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps_ifd, "1st": {}, "thumbnail": None})


CASES = [
    ("01_横版_西湖.jpg", 4000, 3000, "2026:10:26 16:04:22", (30.2541, 120.1503), 1, True),
    ("02_竖拍_苏堤.jpg", 4000, 3000, "2026:10:26 13:52:10", (30.2408, 120.1476), 6, False),
    ("03_无GPS_千岛湖.jpg", 1920, 1080, "2026:10:25 09:18:44", None, 1, True),
    ("04_无EXIF_截图.png", 1280, 720, None, None, 1, False),
    ("05_宽幅_黄山.jpg", 3840, 2160, "2026:10:24 06:41:05", (30.1306, 118.1653), 1, True),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, w, h, taken, gps, orient, warm in CASES:
        path = OUT / name
        img = make_scene(w, h, warm=warm)
        if taken is None:
            img.save(path)
        else:
            img.save(path, quality=92, exif=exif_bytes(taken, gps, orient,
                                                      make="Apple", model="iPhone 15 Pro"))
        print(f"生成 {name}  {w}x{h}")

    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        heif_path = OUT / "06_iPhone原图.heic"
        make_scene(4032, 3024, warm=True).save(
            heif_path, format="HEIF", quality=90,
            exif=exif_bytes("2026:10:26 17:20:00", (30.2592, 120.1385), 1, "Apple", "iPhone 15 Pro"),
        )
        print(f"生成 06_iPhone原图.heic")
    except Exception as exc:
        print(f"HEIC 生成跳过：{exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
