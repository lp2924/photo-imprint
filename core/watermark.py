"""水印绘制：三种样式，都是在照片区域内叠加，不影响原图文件。

字号按照片短边比例算，不写死像素，这样 1200 万和 4800 万像素的照片观感一致。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
_ASSETS_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_REGULAR_NAMES = ("msyh.ttc", "msyhl.ttc", "simhei.ttf", "simsun.ttc",
                  "arial.ttf", "DejaVuSans.ttf")
_BOLD_NAMES = ("msyhbd.ttc", "simhei.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")

STYLE_LABELS = {"A": "无底衬", "B": "半透明条", "C": "拍立得白边"}
STYLE_ORDER = ("B", "A", "C")

# 描边粗细 = 字号 × 比例。以前按 size/15（约 6.7%）画，中文笔画本身才占 ~10%，
# 白边几乎和笔画一样粗，看着像空心字；3% 才是「刚好把字从背景里拔出来」的程度
_STROKE_RATIO = 0.030       # 默认值，界面上的「粗细」滑杆会覆盖它
_STROKE_ALPHA_LIGHT = 165   # 自动配色时，浅色字配黑边的透明度
_STROKE_ALPHA_DARK = 180    # 自动配色时，深色字配白边的透明度

OUTLINE_STYLES = [
    ("none", "无"),
    ("solid", "描边"),
    ("glow", "柔光"),
    ("shadow", "投影"),
]


@dataclass
class WatermarkConfig:
    style: str = "B"
    font_scale: float = 0.034
    margin_scale: float = 0.030
    date_format: str = "%Y.%m.%d %H:%M"
    band_opacity: float = 0.55
    outline_style: str = "solid"                       # none/solid/glow/shadow
    outline_color: tuple[int, int, int] | None = None   # None = 自动取文字反色
    outline_width: float = _STROKE_RATIO                # 描边粗细，相对字号
    color: tuple[int, int, int] = (255, 255, 255)
    position: str = "bottom-left"   # 九宫格位置，见 POSITIONS


def _luma(color: tuple[int, int, int]) -> float:
    r, g, b = color[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def band_fill(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """底条颜色跟着文字走：浅色字配黑条，深色字配白条，否则等于没底衬。"""
    return (0, 0, 0) if _luma(color) > 140 else (255, 255, 255)


def _font_dirs():
    if _ASSETS_FONTS.is_dir():
        yield _ASSETS_FONTS
    yield Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    yield Path("/usr/share/fonts")


def _try_font(path: Path, size: int):
    if not path.is_file():
        return None
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return None


@lru_cache(maxsize=96)
def load_font(size: int, bold: bool = False):
    """优先用 assets/fonts 里自带的字体，保证打包后渲染一致；找不到再退系统字体。"""
    size = max(1, int(size))
    names = _BOLD_NAMES if bold else _REGULAR_NAMES
    for folder in _font_dirs():
        if not folder.is_dir():
            continue
        if folder == _ASSETS_FONTS:
            files = [p for p in folder.iterdir() if p.suffix.lower() in _FONT_SUFFIXES]
            files.sort(key=lambda p: 0 if (("bold" in p.stem.lower()) == bold) else 1)
            for path in files:
                font = _try_font(path, size)
                if font:
                    return font
        for name in names:
            font = _try_font(folder / name, size)
            if font:
                return font
    return ImageFont.load_default(size)


def _metrics(box: tuple[int, int, int, int], cfg: WatermarkConfig) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    short = max(1, min(x1 - x0, y1 - y0))
    size = max(14, min(int(round(short * cfg.font_scale)), 160))
    margin = max(8, int(round(short * cfg.margin_scale)))
    return size, margin


def _build_lines(texts: list[str], size: int):
    main = load_font(size, bold=True)
    sub = load_font(max(10, int(size * 0.88)), bold=False)
    lines = []
    for index, text in enumerate(texts):
        lines.append((text, main if index == 0 else sub))
    return lines


def _layout_lines(lines, gap: int):
    items, total = [], 0
    for text, font in lines:
        bb = font.getbbox(text)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        items.append((text, font, bb, w, h))
        total += h
    if items:
        total += gap * (len(items) - 1)
    return items, total


def _draw_line(draw, x: float, y: float, text: str, font, bb, fill,
               stroke_width: int = 0, stroke_fill=None) -> None:
    # bb 的 y0 是字体内部上沿偏移，减掉才能让多行顶部对齐
    draw.text((x - bb[0], y - bb[1]), text, font=font, fill=fill,
              stroke_width=stroke_width, stroke_fill=stroke_fill)


POSITIONS = [
    ("top-left", "左上"), ("top-center", "上中"), ("top-right", "右上"),
    ("middle-left", "左中"), ("middle-center", "居中"), ("middle-right", "右中"),
    ("bottom-left", "左下"), ("bottom-center", "下中"), ("bottom-right", "右下"),
]


def parse_position(value: str) -> tuple[str, str]:
    """返回 (垂直, 水平)，垂直取 top/middle/bottom，水平取 left/center/right。"""
    parts = (value or "bottom-left").split("-")
    vertical = parts[0] if parts and parts[0] in ("top", "middle", "bottom") else "bottom"
    horizontal = parts[1] if len(parts) > 1 and parts[1] in ("left", "center", "right") else "left"
    return vertical, horizontal


def _place_x(align: str, x0: int, x1: int, width: int, margin: int) -> int:
    if align == "center":
        return x0 + (x1 - x0 - width) // 2
    if align == "right":
        return x1 - margin - width
    return x0 + margin


def _place_y(align: str, y0: int, y1: int, height: int, margin: int) -> int:
    if align == "middle":
        return y0 + (y1 - y0 - height) // 2
    if align == "top":
        return y0 + margin
    return y1 - margin - height


def _auto_outline_color(text_color: tuple[int, int, int]) -> tuple[int, int, int]:
    """没手动指定时取文字的反色：浅字配黑边、深字配白边。"""
    return (0, 0, 0) if _luma(text_color) > 140 else (255, 255, 255)


def _outline_rgba(cfg: WatermarkConfig) -> tuple[int, int, int, int]:
    auto = cfg.outline_color is None
    color = _auto_outline_color(cfg.color) if auto else tuple(cfg.outline_color)
    if not auto:
        alpha = 205      # 自己挑的颜色就别再打折扣，否则等于没生效
    else:
        alpha = _STROKE_ALPHA_LIGHT if _luma(cfg.color) > 140 else _STROKE_ALPHA_DARK
    return color + (alpha,)


def _stroke_px(size: int, cfg: WatermarkConfig) -> int:
    # 描边只负责把字从背景里拔出来，太粗会变成空心字；比例由界面上的「粗细」控制
    return max(1, int(round(size * max(0.004, cfg.outline_width))))


def _paint_soft(img, spots, items, size: int, cfg: WatermarkConfig, mode: str) -> None:
    """柔光 / 投影：把文字画成蒙版、模糊后垫在下面，再盖清晰文字。

    只处理文字外接框那一小块，整图模糊在大照片上太慢。
    """
    ratio = max(0.004, cfg.outline_width)
    radius = max(1, int(round(size * ratio * (3.0 if mode == "glow" else 2.0))))
    shift = 0 if mode == "glow" else max(1, int(round(size * ratio * 1.6)))
    alpha = 150 if cfg.outline_color is None else 195

    width, height = img.size
    xs = [x for x, _ in spots]
    ys = [y for _, y in spots]
    pad = radius * 3 + shift + 2
    left = max(0, min(xs) - pad)
    top = max(0, min(ys) - pad)
    right = min(width, max(x + it[3] for x, it in zip(xs, items)) + pad)
    bottom = min(height, max(y + it[4] for y, it in zip(ys, items)) + pad)
    if right - left < 2 or bottom - top < 2:
        return

    mask = Image.new("L", (right - left, bottom - top), 0)
    mdraw = ImageDraw.Draw(mask)
    for (x, y), (text, font, bb, _w, _h) in zip(spots, items):
        mdraw.text((x - left - bb[0], y - top - bb[1]), text, font=font, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius))

    layer = Image.new("RGBA", mask.size, _outline_rgba(cfg)[:3] + (0,))
    layer.putalpha(mask.point(lambda v: int(v * alpha / 255)))
    img.paste(layer, (left + shift, top + shift), layer)


def _render_text(img, spots, items, size: int, cfg: WatermarkConfig) -> None:
    """spots 与 items 一一对应，给出每行文字的左上角坐标。"""
    style = cfg.outline_style if cfg.outline_style in ("none", "solid", "glow", "shadow") else "solid"
    if style in ("glow", "shadow"):
        _paint_soft(img, spots, items, size, cfg, style)
        stroke_w, stroke = 0, None
    elif style == "solid":
        stroke_w, stroke = _stroke_px(size, cfg), _outline_rgba(cfg)
    else:
        stroke_w, stroke = 0, None

    draw = ImageDraw.Draw(img, "RGBA")
    for (x, y), (text, font, bb, _w, _h) in zip(spots, items):
        _draw_line(draw, x, y, text, font, bb, cfg.color + (255,), stroke_w, stroke)


def _paint_plain(img, box, lines, size: int, margin: int, cfg: WatermarkConfig) -> None:
    x0, y0, x1, y1 = box
    vertical, horizontal = parse_position(cfg.position)
    gap = int(round(size * 0.45))
    items, total = _layout_lines(lines, gap)
    y = _place_y(vertical, y0, y1, total, margin)
    spots = []
    for _text, _font, _bb, line_w, line_h in items:
        spots.append((_place_x(horizontal, x0, x1, line_w, margin), y))
        y += line_h + gap
    _render_text(img, spots, items, size, cfg)


def _band_layer(width: int, height: int, opacity: float,
                fill: tuple[int, int, int] = (0, 0, 0),
                flip: bool = False, flat: bool = False) -> Image.Image:
    """渐变条：默认底部条上沿透明过渡，flip 后改成顶部条下沿过渡。

    flat 用于居中位置——条子上下都不贴边，渐变会留出一道硬边，改用均匀半透明。
    """
    max_alpha = int(255 * max(0.0, min(1.0, opacity)))
    if flat:
        return Image.new("RGBA", (width, height), fill + (max_alpha,))
    knee = max(1, int(height * 0.55))
    ramp = Image.new("L", (1, height), 0)
    for i in range(height):
        ramp.putpixel((0, i), int(max_alpha * min(1.0, i / knee)))
    if flip:
        ramp = ramp.transpose(Image.FLIP_TOP_BOTTOM)
    ramp = ramp.resize((width, height), Image.BILINEAR)
    layer = Image.new("RGBA", (width, height), fill + (255,))
    layer.putalpha(ramp)
    return layer


def _paint_band(img, box, lines, size: int, margin: int, cfg: WatermarkConfig) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    vertical, horizontal = parse_position(cfg.position)
    gap = int(round(size * 0.45))
    items, total = _layout_lines(lines, gap)
    pad_v = int(round(size * 0.6))
    band_h = min(total + pad_v * 2, int((y1 - y0) * 0.34))

    if vertical == "top":
        band_top, flip = y0, True
    elif vertical == "middle":
        band_top, flip = y0 + ((y1 - y0) - band_h) // 2, False
    else:
        band_top, flip = y1 - band_h, False

    # 深色文字配白条时要更实，半透明白条压不住浅色背景
    opacity = cfg.band_opacity if _luma(cfg.color) > 140 else min(0.85, cfg.band_opacity + 0.2)
    band = _band_layer(width, band_h, opacity, band_fill(cfg.color), flip,
                       flat=(vertical == "middle"))
    img.paste(band, (x0, band_top), band)

    spots = []
    y = band_top + (band_h - total) // 2
    for _text, _font, _bb, line_w, line_h in items:
        spots.append((_place_x(horizontal, x0, x1, line_w, margin), y))
        y += line_h + gap
    _render_text(img, spots, items, size, cfg)


def _paint_polaroid_expand(img, box, lines, size: int, cfg: WatermarkConfig):
    """四周扩白边，只在"原图"模式下用——没有纸型约束才可以自由变大。"""
    x0, y0, x1, y1 = box
    vertical, horizontal = parse_position(cfg.position)
    gap = int(round(size * 0.45))
    items, total = _layout_lines(lines, gap)

    photo_w, photo_h = x1 - x0, y1 - y0
    border = max(6, int(round(min(photo_w, photo_h) * 0.028)))
    extra = border + total + gap
    w, h = img.size

    if vertical == "top":
        canvas = Image.new("RGB", (w + border * 2, h + border + extra), (255, 255, 255))
        canvas.paste(img, (border, extra))
        new_box = (x0 + border, y0 + extra, x1 + border, y1 + extra)
        text_y = border + gap // 2
    else:
        canvas = Image.new("RGB", (w + border * 2, h + border + extra), (255, 255, 255))
        canvas.paste(img, (border, border))
        new_box = (x0 + border, y0 + border, x1 + border, y1 + border)
        text_y = new_box[3] + gap // 2

    spots = []
    for _text, _font, _bb, line_w, line_h in items:
        spots.append((_place_x(horizontal, new_box[0], new_box[2], line_w, 0), text_y))
        text_y += line_h + gap
    _render_text(canvas, spots, items, size, cfg)
    return canvas, new_box


def _paint_polaroid_inline(img, box, lines, size: int, cfg: WatermarkConfig) -> None:
    """白边已由 layout 预留，这里只把字写到照片上/下方的白边里。"""
    x0, y0, x1, y1 = box
    vertical, horizontal = parse_position(cfg.position)
    gap = int(round(size * 0.45))
    items, total = _layout_lines(lines, gap)

    # 白边里垂直居中，不然字会紧贴照片边缘
    if vertical == "top":
        y = max(int(size * 0.15), (y0 - total) // 2)
    else:
        band = max(0, img.size[1] - y1)
        y = y1 + max(gap // 2, (band - total) // 2)

    spots = []
    for _text, _font, _bb, line_w, line_h in items:
        spots.append((_place_x(horizontal, x0, x1, line_w, 0), y))
        y += line_h + gap
    _render_text(img, spots, items, size, cfg)


def _fit_size(box: tuple[int, int, int, int], texts: list[str],
              cfg: WatermarkConfig) -> tuple[int, int]:
    """地址长度不可控，超宽时按比例缩字号，避免长地名顶出画面。"""
    size, margin = _metrics(box, cfg)
    x0, _y0, x1, _y1 = box
    limit = (x1 - x0) - margin * 2
    while size > 12:
        lines = _build_lines(texts, size)
        widest = max(font.getbbox(t)[2] - font.getbbox(t)[0] for t, font in lines)
        if widest <= limit:
            break
        size = int(size * 0.92)
    return size, margin


def apply(img: Image.Image, box: tuple[int, int, int, int], texts: list[str],
          cfg: WatermarkConfig, polaroid_mode: str = "expand"
          ) -> tuple[Image.Image, tuple[int, int, int, int]]:
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return img, box

    size, margin = _fit_size(box, texts, cfg)
    lines = _build_lines(texts, size)

    if cfg.style == "C":
        if polaroid_mode == "inline":
            _paint_polaroid_inline(img, box, lines, size, cfg)
            return img, box
        return _paint_polaroid_expand(img, box, lines, size, cfg)
    if cfg.style == "B":
        _paint_band(img, box, lines, size, margin, cfg)
    else:
        _paint_plain(img, box, lines, size, margin, cfg)
    return img, box
