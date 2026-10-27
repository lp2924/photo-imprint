"""纸型适配。

策略是"补白不裁切"：照片按原比例缩放后居中贴到纸型画布上，空白填白。
打印店按尺寸冲印时 0 裁切，水印永远不会被切掉。
"""

from __future__ import annotations

from PIL import Image

# 300 dpi 下的长边 × 短边像素
PAPER_PRESETS: dict[str, tuple[int, int] | None] = {
    "原图": None,
    "5寸": (1500, 1050),
    "6寸": (1800, 1200),
    "7寸": (2100, 1500),
    "A4": (3508, 2480),
}

DEFAULT_PAPER = "6寸"


def target_size(preset: tuple[int, int] | None, size: tuple[int, int]) -> tuple[int, int]:
    """相纸方向跟着照片走：横片用横纸，竖片用竖纸。"""
    if preset is None:
        return size
    long_side, short_side = preset
    w, h = size
    return (long_side, short_side) if w >= h else (short_side, long_side)


def polaroid_frame(size: tuple[int, int], border_scale: float = 0.035,
                   bottom_scale: float = 0.11, top: bool = False) -> tuple[int, int, int, int]:
    """拍立得白边的内缩量。文字区高度按画布短边比例给，固定比例才能一次算准。"""
    w, h = size
    short = min(w, h)
    border = max(4, int(round(short * border_scale)))
    band = max(24, int(round(short * bottom_scale)))
    # 文字在上方白边时，宽边给顶部
    return (border, border + band, border, border) if top else (border, border, border, border + band)


def prepare(img: Image.Image, paper: str = DEFAULT_PAPER,
            frame: tuple[int, int, int, int] = (0, 0, 0, 0),
            mode: str = "pad") -> tuple[Image.Image, tuple[int, int, int, int]]:
    """返回 (画布, 照片区域)。照片区域用于限定水印绘制范围。

    frame 是在画布内部预留的白边，输出尺寸始终等于纸型尺寸。
    mode="pad" 补白不裁切（水印绝不被切）；mode="crop" 居中裁切铺满（无水印白边）。
    """
    preset = PAPER_PRESETS.get(paper)
    if preset is None:
        return img, (0, 0, img.width, img.height)

    tw, th = target_size(preset, img.size)
    left, top, right, bottom = frame
    avail_w = max(1, tw - left - right)
    avail_h = max(1, th - top - bottom)

    scale = (max if mode == "crop" else min)(avail_w / img.width, avail_h / img.height)
    nw = max(1, round(img.width * scale))
    nh = max(1, round(img.height * scale))
    resized = img if (nw, nh) == img.size else img.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGB", (tw, th), (255, 255, 255))
    ox = left + (avail_w - nw) // 2
    oy = top + (avail_h - nh) // 2

    if mode != "crop":
        canvas.paste(resized, (ox, oy))
        return canvas, (ox, oy, ox + nw, oy + nh)

    src_x, src_y = max(0, -ox), max(0, -oy)
    dst_x, dst_y = max(0, ox), max(0, oy)
    piece_w = min(nw - src_x, tw - right - dst_x)
    piece_h = min(nh - src_y, th - bottom - dst_y)
    piece = resized.crop((src_x, src_y, src_x + piece_w, src_y + piece_h))
    canvas.paste(piece, (dst_x, dst_y))
    return canvas, (dst_x, dst_y, dst_x + piece_w, dst_y + piece_h)


def expand(canvas: Image.Image, box: tuple[int, int, int, int],
           pad: tuple[int, int, int, int], color=(255, 255, 255)):
    """四周扩白边，返回 (新画布, 平移后的照片区域)。"""
    left, top, right, bottom = pad
    w, h = canvas.size
    out = Image.new("RGB", (w + left + right, h + top + bottom), color)
    out.paste(canvas, (left, top))
    x0, y0, x1, y1 = box
    return out, (x0 + left, y0 + top, x1 + left, y1 + top)
