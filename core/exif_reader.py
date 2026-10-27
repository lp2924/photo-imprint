"""EXIF 提取：拍摄时间、GPS 坐标、方向、相机型号。

只负责"读"，不改图。所有异常都收敛成默认值，单张照片坏掉不应中断整批。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    # 没装 pillow-heif 时 HEIC 会读不出来，其余格式不受影响
    HEIF_SUPPORTED = False

SUPPORTED_SUFFIXES = {
    ".jpg", ".jpeg", ".jpe", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff",
}

_TAG_DATETIME_ORIGINAL = 36867
_TAG_DATETIME = 306
_TAG_MAKE = 271
_TAG_MODEL = 272
_TAG_ORIENTATION = 274
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825

_DATETIME_FORMATS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y:%m:%d %H:%M",
    "%Y-%m-%d %H:%M",
)


@dataclass
class PhotoMeta:
    taken_at: dt.datetime | None = None
    gps: tuple[float, float] | None = None  # (纬度, 经度)，WGS-84
    make: str = ""
    model: str = ""
    orientation: int = 1
    taken_source: str = "missing"  # exif / file / missing

    @property
    def camera(self) -> str:
        return " ".join(p for p in (self.make, self.model) if p).strip()

    @property
    def has_gps(self) -> bool:
        return self.gps is not None


def _parse_datetime(value) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().strip("\x00")
    for fmt in _DATETIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _to_degrees(values, ref: str) -> float | None:
    """EXIF 的经纬度是 (度, 分, 秒) 三段有理数，转成十进制角度。"""
    try:
        parts = [float(v) for v in list(values)[:3]]
    except (TypeError, ValueError):
        return None
    if len(parts) < 2:
        return None
    deg = parts[0] + parts[1] / 60.0 + (parts[2] / 3600.0 if len(parts) > 2 else 0.0)
    return -deg if str(ref).upper() in ("S", "W") else deg


def _read_datetime(exif) -> dt.datetime | None:
    # DateTimeOriginal 在 Exif 子 IFD 里，顶层 get 取不到，很容易踩空退回文件时间
    try:
        sub = exif.get_ifd(_TAG_EXIF_IFD)
    except Exception:
        sub = {}
    for source in (sub, exif):
        if not source:
            continue
        for tag in (_TAG_DATETIME_ORIGINAL, _TAG_DATETIME):
            parsed = _parse_datetime(source.get(tag))
            if parsed is not None:
                return parsed
    return None


def _read_gps(exif) -> tuple[float, float] | None:
    try:
        gps = exif.get_ifd(_TAG_GPS_IFD)
    except Exception:
        return None
    if not gps:
        return None
    lat = _to_degrees(gps.get(2, ()), gps.get(1, "N"))
    lon = _to_degrees(gps.get(4, ()), gps.get(3, "E"))
    if lat is None or lon is None:
        return None
    # 有些相机写了全 0 占位，当成没有坐标处理
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _get_exif(img: Image.Image):
    exif = img.getexif()
    if exif:
        return exif
    raw = img.info.get("exif")
    if raw:
        try:
            loaded = Image.Exif()
            loaded.load(raw)
            return loaded
        except Exception:
            pass
    return exif


def _file_time(path: Path) -> dt.datetime | None:
    for attr in ("st_mtime", "st_ctime"):
        try:
            return dt.datetime.fromtimestamp(getattr(path.stat(), attr))
        except OSError:
            continue
    return None


def read_meta(path: Path) -> PhotoMeta:
    meta = PhotoMeta()
    try:
        with Image.open(path) as img:
            exif = _get_exif(img)
            if exif:
                meta.make = str(exif.get(_TAG_MAKE, "") or "").strip()
                meta.model = str(exif.get(_TAG_MODEL, "") or "").strip()
                try:
                    meta.orientation = int(exif.get(_TAG_ORIENTATION, 1) or 1)
                except (TypeError, ValueError):
                    meta.orientation = 1
                meta.taken_at = _read_datetime(exif)
                if meta.taken_at is not None:
                    meta.taken_source = "exif"
                meta.gps = _read_gps(exif)
    except Exception:
        pass

    if meta.taken_at is None:
        meta.taken_at = _file_time(path)
        meta.taken_source = "file"
    return meta


def load_image(path: Path) -> Image.Image:
    """打开图片并摆正。exif_transpose 必须最先做，否则竖拍照片的水印会横着画。"""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            return img.convert("RGB")
        return img.copy()
