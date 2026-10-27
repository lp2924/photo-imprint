"""GPS 坐标转地名。

关键点：EXIF 里是 WGS-84，高德要 GCJ-02。不做转换会偏几百米，
明明在西湖却返回隔壁街道，所以转换是必做项而不是可选优化。
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import requests

_AMAP_REGEO = "https://restapi.amap.com/v3/geocode/regeo"
_REQUEST_TIMEOUT = 6

_A = 6378245.0
_EE = 0.00669342162296594323
_GRID = 0.005  # 缓存网格约 500 米，同一景点只查一次


def _out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84 转 GCJ-02。境外坐标不做偏移，原样返回。"""
    if _out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return lng + d_lng, lat + d_lat


def _text(value) -> str:
    # 高德在"直辖市"等场景会返回空数组而不是字符串
    if isinstance(value, list):
        return ""
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


# 少数省级行政区去掉后缀还剩一长串，直接给通用简称
_SHORT_ADMIN = {
    "内蒙古自治区": "内蒙古",
    "广西壮族自治区": "广西",
    "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "香港特别行政区": "香港",
    "澳门特别行政区": "澳门",
}

# 去掉后缀还剩 2~5 个字的才动刀：短名不歧义；"阿坝藏族羌族自治州"砍完整串反而读不通，保留原样
_STRIP_SUFFIXES = ("自治区", "特别行政区", "自治州", "自治县", "自治旗",
                   "新区", "地区", "省", "市", "区", "县", "旗")


def _short(name: str) -> str:
    if not name:
        return ""
    alias = _SHORT_ADMIN.get(name)
    if alias:
        return alias
    for suffix in _STRIP_SUFFIXES:
        if name.endswith(suffix):
            rest = name[: -len(suffix)]
            return rest if 2 <= len(rest) <= 5 else name
    return name


# 地名层级：勾哪几档就拼哪几档，顺序固定由粗到细
PLACE_SLOTS = (
    ("province", "省"),
    ("city", "市"),
    ("district", "区县"),
    ("township", "街道"),
    ("road", "门牌"),
)
SLOT_KEYS = tuple(key for key, _ in PLACE_SLOTS)
_ADMIN_SLOTS = {"province", "city", "district"}
# 高德会拿这些占位串顶上，念出来是废话
_DROP_TEXTS = {"市辖区", "直辖县级行政区划", "省直辖县级行政区划"}
DEFAULT_SLOTS = ("province", "city", "district")

# 预设档位：命令行 --place-detail 和旧版配置里存的就是这几个词
PRESET_SLOTS = {
    "city": ("province", "city"),
    "district": ("province", "city", "district"),
    "street": ("province", "city", "district", "township"),
    "full": SLOT_KEYS,
}
DETAIL_LEVELS = tuple(PRESET_SLOTS)
DETAIL_LABELS = {
    "city": "省市（甘肃 白银）",
    "district": "省市区县（甘肃 白银 会宁）",
    "street": "到街道/乡镇",
    "full": "含道路门牌",
}

# 同一批层级有两种写法：短写去后缀加空格，全称原样连写
PLACE_STYLES = (("short", "短写"), ("full", "全称"))
STYLE_KEYS = tuple(key for key, _ in PLACE_STYLES)
DEFAULT_STYLE = "short"


def normalize_slots(slots) -> tuple[str, ...]:
    """配置里可能存预设档位名，也可能是层级 key 列表，统一成有序 key 元组。"""
    if isinstance(slots, str):
        return PRESET_SLOTS.get(slots, DEFAULT_SLOTS)
    picked = tuple(key for key in SLOT_KEYS if key in set(slots or ()))
    return picked or DEFAULT_SLOTS


def compose_place(parts: dict[str, str], slots=DEFAULT_SLOTS, style: str = DEFAULT_STYLE) -> str:
    """按勾选的层级拼地名。

    短写：("province","district") → "甘肃 会宁"
    全称：("province","city","district") → "甘肃省白银市会宁县"
    """
    full = style == "full"
    words: list[str] = []
    for slot in normalize_slots(slots):
        raw = parts.get(slot, "").strip()
        if slot == "road":
            raw = f"{raw}{parts.get('number', '')}".strip()
        # 空档不占位；占位串不要（要在去后缀之前判，否则"市辖区"会被砍成"市辖"）
        if not raw or raw in _DROP_TEXTS or "直辖县级" in raw:
            continue
        text = raw if full or slot not in _ADMIN_SLOTS else _short(raw)
        if words and text == words[-1]:
            continue  # 直辖市的省和市是同一个词
        words.append(text)
    return "".join(words) if full else " ".join(words)


def _compose_parts(comp: dict) -> dict[str, str]:
    """地址组件拆成层级字典存缓存，之后想拼哪几档都不用再调 API。"""
    prov = _text(comp.get("province"))
    street_no = comp.get("streetNumber") or {}
    return {
        "province": prov,
        # 直辖市 city 返回空数组，补成省名，免得只勾「市」时反而空白
        "city": _text(comp.get("city")) or prov,
        "district": _text(comp.get("district")),
        "township": _text(comp.get("township")),
        "road": _text(street_no.get("street")),
        "number": _text(street_no.get("number")),
    }


def _has_address(parts: dict[str, str]) -> bool:
    return bool(parts.get("province") or parts.get("district") or parts.get("township"))


class GeoResolver:
    """把 (纬度, 经度) 换成中文地名，带磁盘缓存。"""

    def __init__(self, api_key: str = "", cache_file: Path | str | None = None,
                 offline_fallback: str = "coords"):
        self.api_key = (api_key or "").strip()
        self.cache_file = Path(cache_file) if cache_file else None
        self.offline_fallback = offline_fallback  # coords / none
        self._cache: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self.last_error = ""
        self._load_cache()

    @staticmethod
    def cache_key(lat: float, lon: float) -> str:
        return f"{round(lat / _GRID)},{round(lon / _GRID)}"

    def _load_cache(self) -> None:
        if not self.cache_file or not self.cache_file.is_file():
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            # 旧版只存了拼好的字符串，还原不出层级，丢弃让下次重查
            if isinstance(value, dict) and "province" in value:
                self._cache[str(key)] = {k: str(v) for k, v in value.items() if v}

    def save_cache(self) -> None:
        if not self.cache_file or not self._dirty:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            self._dirty = False
        except OSError:
            pass

    def resolve(self, lat: float, lon: float, slots=DEFAULT_SLOTS,
                style: str = DEFAULT_STYLE) -> str:
        """slots 传层级 key 列表或旧版档位名，拼出这一张要显示的地名。"""
        key = self.cache_key(lat, lon)
        with self._lock:
            entry = self._cache.get(key)
        if entry:
            return compose_place(entry, slots, style)

        parts = self._query_amap(lat, lon) if self.api_key else {}
        if parts:
            # 只缓存真实地址；坐标兜底不进缓存，否则以后配了 Key 还会一直返回坐标
            with self._lock:
                self._cache[key] = parts
                self._dirty = True
            return compose_place(parts, slots, style)
        return self._fallback(lat, lon)

    def _query_amap(self, lat: float, lon: float) -> dict[str, str]:
        lng_g, lat_g = wgs84_to_gcj02(lon, lat)
        params = {
            "key": self.api_key,
            "location": f"{lng_g:.6f},{lat_g:.6f}",
            "extensions": "base",
            "radius": 1000,
        }
        try:
            resp = requests.get(_AMAP_REGEO, params=params, timeout=_REQUEST_TIMEOUT)
            data = resp.json()
        except Exception as exc:
            self.last_error = f"请求失败: {exc}"
            return {}
        if str(data.get("status")) != "1":
            self.last_error = f"高德返回: {data.get('info')} ({data.get('infocode')})"
            return {}
        regeo = data.get("regeocode") or {}
        parts = _compose_parts(regeo.get("addressComponent") or {})
        return parts if _has_address(parts) else {}

    def _fallback(self, lat: float, lon: float) -> str:
        if self.offline_fallback == "none":
            return ""
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        return f"{abs(lat):.4f}°{ns} {abs(lon):.4f}°{ew}"
