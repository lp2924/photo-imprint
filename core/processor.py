"""批处理：扫描、渲染、命名、落盘。"""

from __future__ import annotations

import datetime as dt
import re
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import exif_reader, geo, layout, watermark
from .geo import GeoResolver

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\s°]+')
_name_lock = threading.Lock()


@dataclass
class JobConfig:
    output_dir: Path
    style: str = "B"
    paper: str = layout.DEFAULT_PAPER
    fill_mode: str = "pad"            # pad 补白不裁切 / crop 裁切铺满
    place_mode: str = "auto"          # auto 读 EXIF GPS / manual 全批统一
    manual_place: str = ""            # 手动地点，同时作为无 GPS 时的兜底
    # 地名要显示到哪几级：province/city/district/township/road 里勾哪些拼哪些
    place_slots: tuple[str, ...] = geo.DEFAULT_SLOTS
    place_style: str = geo.DEFAULT_STYLE   # short 短写 / full 全称连写
    date_format: str = "%Y.%m.%d %H:%M"   # 留空则不显示时间
    font_scale: float = 0.034
    band_opacity: float = 0.55
    outline_style: str = "solid"                       # none/solid/glow/shadow
    outline_color: tuple[int, int, int] | None = None   # None = 自动反色
    outline_width: float = watermark._STROKE_RATIO      # 描边粗细，相对字号
    color: tuple[int, int, int] = (255, 255, 255)
    position: str = "bottom-left"
    jpeg_quality: int = 95
    recursive: bool = True
    name_by_time: bool = True
    keep_structure: bool = True
    overwrite: bool = False

    def watermark_config(self) -> watermark.WatermarkConfig:
        return watermark.WatermarkConfig(
            style=self.style,
            font_scale=self.font_scale,
            date_format=self.date_format,
            band_opacity=self.band_opacity,
            outline_style=self.outline_style,
            outline_color=self.outline_color,
            outline_width=self.outline_width,
            color=self.color,
            position=self.position,
        )


@dataclass
class JobResult:
    src: Path
    dst: Path | None = None
    ok: bool = False
    error: str = ""
    place: str = ""
    taken_at: dt.datetime | None = None
    from_gps: bool = False


def _within(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def collect_files(input_dir: Path, recursive: bool = True,
                  exclude: Iterable[Path] = ()) -> list[Path]:
    """扫描待处理照片。

    exclude 用来排除输出目录：默认输出到输入目录下的 out，不排除的话第二次扫描
    会把上一轮加了水印的成品当原图再盖一遍。
    """
    if not input_dir.is_dir():
        return []
    root = input_dir.resolve()
    skip = []
    for item in exclude:
        try:
            folder = Path(item).resolve()
        except OSError:
            continue
        if folder != root:  # 输出目录就是输入目录时不排除，否则会扫成空
            skip.append(folder)

    pattern = "**/*" if recursive else "*"
    files = []
    for path in input_dir.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in exif_reader.SUPPORTED_SUFFIXES:
            continue
        if skip and any(_within(path.resolve(), folder) for folder in skip):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.name.lower())


def _safe_name(text: str, limit: int = 16) -> str:
    cleaned = _INVALID_CHARS.sub("", text).strip()
    return cleaned[:limit] or "未标注"


def resolve_place(meta: exif_reader.PhotoMeta, cfg: JobConfig,
                  resolver: GeoResolver | None) -> tuple[str, bool]:
    """返回 (地名, 是否来自 GPS)。手动模式优先，无 GPS 时也退回手动地点。"""
    manual = cfg.manual_place.strip()
    if cfg.place_mode == "manual":
        return manual, False
    if meta.gps and resolver is not None:
        place = resolver.resolve(meta.gps[0], meta.gps[1], cfg.place_slots, cfg.place_style)
        if place:
            return place, True
    return manual, False


def _output_stem(src: Path, meta: exif_reader.PhotoMeta, place: str, cfg: JobConfig) -> str:
    if not cfg.name_by_time:
        return f"{src.stem}_印迹"
    date = meta.taken_at.strftime("%Y-%m-%d_%H%M") if meta.taken_at else "未知时间"
    return f"{date}_{_safe_name(place)}"


def _reserve_path(directory: Path, stem: str, overwrite: bool) -> Path:
    """在锁内完成"查重 + 占位"。

    同一分钟内连拍的照片输出名完全一样，多线程各自判断"不存在"会撞到同一个文件，
    所以必须原子地创建占位文件把名字占住。
    """
    with _name_lock:
        if overwrite:
            return directory / f"{stem}.jpg"
        index = 1
        while True:
            path = directory / (f"{stem}.jpg" if index == 1 else f"{stem}_{index}.jpg")
            if not path.exists():
                try:
                    path.touch(exist_ok=False)
                    return path
                except FileExistsError:
                    pass
            index += 1


def render(src: Path, cfg: JobConfig, resolver: GeoResolver | None = None, cap: int | None = None):
    """渲染但不落盘。cap 用于界面预览降采样，按等比缩小后字号观感一致。"""
    meta = exif_reader.read_meta(src)
    place, from_gps = resolve_place(meta, cfg, resolver)
    image = exif_reader.load_image(src)
    if cap and max(image.size) > cap:
        image.thumbnail((cap, cap), Image.LANCZOS)

    frame = (0, 0, 0, 0)
    polaroid_mode = "expand"
    preset = layout.PAPER_PRESETS.get(cfg.paper)
    if cfg.style == "C" and preset is not None:
        # 有纸型时把白边做在画布内部，保证输出尺寸严格等于纸型尺寸
        vertical, _h = watermark.parse_position(cfg.position)
        frame = layout.polaroid_frame(layout.target_size(preset, image.size),
                                      top=(vertical == "top"))
        polaroid_mode = "inline"

    canvas, box = layout.prepare(image, cfg.paper, frame, cfg.fill_mode)
    time_text = ""
    if meta.taken_at and cfg.date_format:
        time_text = meta.taken_at.strftime(cfg.date_format)
    canvas, _box = watermark.apply(canvas, box, [time_text, place],
                                   cfg.watermark_config(), polaroid_mode)
    return canvas, meta, place, from_gps


def process_one(src: Path, cfg: JobConfig, resolver: GeoResolver | None = None,
                input_root: Path | None = None) -> JobResult:
    result = JobResult(src=src)
    try:
        canvas, meta, place, from_gps = render(src, cfg, resolver)
        result.place = place
        result.taken_at = meta.taken_at
        result.from_gps = from_gps

        out_dir = Path(cfg.output_dir)
        if cfg.keep_structure and input_root is not None:
            try:
                rel = src.parent.relative_to(input_root)
                if str(rel) not in ("", "."):
                    out_dir = out_dir / rel
            except ValueError:
                pass
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = _output_stem(src, meta, place, cfg)
        dst = _reserve_path(out_dir, stem, cfg.overwrite)
        try:
            canvas.save(dst, "JPEG", quality=cfg.jpeg_quality, subsampling=0,
                        dpi=(300, 300), optimize=True)
        except Exception:
            dst.unlink(missing_ok=True)  # 失败时清掉占位，别留下空文件
            raise
        result.dst = dst
        result.ok = True
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def process_batch(files: list[Path], cfg: JobConfig, resolver: GeoResolver | None = None,
                  input_root: Path | None = None, on_progress=None,
                  workers: int = 4) -> list[JobResult]:
    total = len(files)
    results: list[JobResult] = []
    if not total:
        return results

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(process_one, path, cfg, resolver, input_root): path for path in files
        }
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(done, total, result)

    if resolver is not None:
        resolver.save_cache()
    return results
