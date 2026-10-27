"""生成图标资源：assets/app.ico（窗口/任务栏）与 assets/settings.ico（设置弹窗）。

    python tools/make_icon.py

app：蓝色底 + 白照片 + 底部白条，一眼看出是给照片加条水印的工具，
16px 下也只剩三个大色块，不会糊成一团。
settings：齿轮。设置弹窗挂应用图标会显得像又一个主窗口，齿轮更能说明"这是设置"。
"""

from __future__ import annotations

import math
import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZES = (256, 128, 64, 48, 32, 24, 16)
# 256 用 PNG 压缩（Windows 从 Vista 起支持），更小的层一律用 BMP：
# 资源管理器的"小图标"视图读不了 PNG 编码的小层，会退回旧缓存或空白
PNG_SIZE = 256

BG_TOP = (31, 111, 190)
BG_BOTTOM = (19, 76, 122)
SKY = (215, 233, 246)
HILL = (127, 169, 204)
SUN = (242, 193, 78)
LINE = (155, 176, 194)
WHITE = (255, 255, 255)


def _rounded(size: int, radius: int, fill) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=fill)
    return layer


def _dib(img: Image.Image) -> bytes:
    """RGBA → 32bpp BMP（BITMAPINFOHEADER + XOR 位图 + AND 掩码），行序自下而上。"""
    w, h = img.size
    px = img.load()
    mask_stride = ((w + 31) // 32) * 4
    xor = bytearray()
    and_mask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(mask_stride)
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))
            if a == 0:  # 掩码里 1 = 透明，给不认 alpha 的旧代码路径兜底
                bits[x // 8] |= 0x80 >> (x % 8)
        and_mask += bits
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + bytes(and_mask)


def write_ico(path: Path, artwork: Image.Image, sizes=SIZES) -> None:
    """自己写 ICO：小尺寸存 BMP，256 存 PNG。

    Pillow 的 save(sizes=...) 会把每一层都压成 PNG，资源管理器小图标视图读不出来。
    """
    layers = []
    for size in sorted(sizes):
        frame = artwork if size == artwork.width else artwork.resize((size, size), Image.LANCZOS)
        if size >= PNG_SIZE:
            buf = BytesIO()
            frame.save(buf, "PNG")
            layers.append((size, buf.getvalue()))
        else:
            layers.append((size, _dib(frame)))

    offset = 6 + 16 * len(layers)
    entries, blobs = b"", b""
    for size, data in layers:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(layers)) + entries + blobs)


def build(scale: int = 4) -> Image.Image:
    s = 256 * scale
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 背景：竖向渐变 + 圆角
    grad = Image.new("RGBA", (s, s))
    draw = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / (s - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        draw.line([(0, y), (s, y)], fill=color + (255,))
    canvas.paste(grad, (0, 0), _rounded(s, int(s * 0.22), (255, 255, 255, 255)))

    # 照片：白色圆角卡片，里面画个极简风景
    px0, py0, px1, py1 = int(s * 0.147), int(s * 0.164), int(s * 0.853), int(s * 0.637)
    card_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle((px0, py0, px1, py1), int(s * 0.05), fill=255)
    scene = Image.new("RGBA", (s, s), SKY + (255,))
    sd = ImageDraw.Draw(scene)
    sd.polygon([(px0, py1), (int(s * 0.40), int(s * 0.34)), (int(s * 0.60), py1)], fill=HILL + (255,))
    sd.polygon([(int(s * 0.34), py1), (int(s * 0.62), int(s * 0.40)),
                (int(s * 0.86), py1)], fill=tuple(int(c * 0.85) for c in HILL) + (255,))
    sd.ellipse((int(s * 0.64), int(s * 0.25), int(s * 0.78), int(s * 0.25) + int(s * 0.14)),
               fill=SUN + (255,))
    canvas.paste(scene, (0, 0), card_mask)
    ImageDraw.Draw(canvas).rounded_rectangle((px0, py0, px1, py1), int(s * 0.05),
                                             outline=WHITE + (255,), width=int(s * 0.012))

    # 底部白条 = 水印条，里面两行"文字"
    bx0, by0, bx1, by1 = int(s * 0.147), int(s * 0.675), int(s * 0.853), int(s * 0.836)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((bx0, by0, bx1, by1), int(s * 0.038), fill=WHITE + (255,))
    bar_h = by1 - by0
    for index, ratio in enumerate((0.52, 0.34)):
        y = by0 + bar_h * (0.30 if index == 0 else 0.60)
        d.rounded_rectangle((bx0 + s * 0.055, y, bx0 + s * 0.055 + (bx1 - bx0) * ratio,
                             y + bar_h * 0.16),
                            int(bar_h * 0.08), fill=LINE + (255,))

    return canvas.resize((256, 256), Image.LANCZOS)


def build_gear(scale: int = 4) -> Image.Image:
    """齿轮：8 个齿 + 中心圆孔，蓝色实心，透明背景。"""
    s = 256 * scale
    cx = cy = s / 2
    r_out, r_root, r_hole = s * 0.48, s * 0.36, s * 0.155
    teeth, tooth_half, gap_half = 8, 0.20, 0.30   # 弧度：齿顶半宽 / 齿根半宽

    points = []
    for i in range(teeth):
        base = 2 * math.pi * i / teeth
        for angle, radius in (
            (base - gap_half, r_root),
            (base - tooth_half, r_out),
            (base + tooth_half, r_out),
            (base + gap_half, r_root),
        ):
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.polygon(points, fill=BG_TOP + (255,))
    draw.ellipse((cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole), fill=(0, 0, 0, 0))
    return canvas.resize((256, 256), Image.LANCZOS)


def main() -> int:
    big = build()
    gear = build_gear()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    write_ico(assets / "app.ico", big)
    big.save(assets / "app.png")
    write_ico(assets / "settings.ico", gear)
    gear.save(assets / "settings.png")

    # 预览：大尺寸和缩到 16px 的样子并排，确认小图标还认得出
    sheet = Image.new("RGBA", (640, 110), (245, 244, 240, 255))
    for index, (icon, sizes) in enumerate(((big, (96, 48, 32, 16)), (gear, (96, 48, 32, 16)))):
        x = 12 + index * 320
        for n in sizes:
            small = icon.resize((n, n), Image.LANCZOS)
            sheet.paste(small, (x, (110 - n) // 2), small)
            x += n + 12
    sheet.save(ROOT / "samples" / "icon_preview.png")
    print("saved assets/app.ico, assets/settings.ico, samples/icon_preview.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
