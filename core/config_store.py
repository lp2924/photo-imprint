"""config.json 的读写。

高德 Key 落盘前用 DPAPI 加密，其余设置保持明文（方便手看手改）。
旧版本留下的明文 api_key 会在第一次读取时自动加密并抹掉。
"""

from __future__ import annotations

import json
import os

from . import secret
from .paths import CONFIG_FILE

ENV_KEY = "PHOTOIMPRINT_AMAP_KEY"
_PLAIN_FIELD = "api_key"
_ENC_FIELD = "api_key_enc"


def _read_file() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config() -> dict:
    data = _read_file()
    plain = str(data.get(_PLAIN_FIELD) or "").strip()
    if plain and not data.get(_ENC_FIELD):
        save_config({**data, _PLAIN_FIELD: plain})  # 顺手把旧明文迁成密文
    return data


def save_config(data: dict) -> None:
    """传进来的 dict 里带明文 api_key 也没关系，写盘前会被换成密文。"""
    payload = dict(data)
    key = str(payload.pop(_PLAIN_FIELD, "") or "").strip()
    payload.pop(_ENC_FIELD, None)
    encrypted = secret.protect(key) if key else ""
    if encrypted:
        payload[_ENC_FIELD] = encrypted
    elif key:
        # 万一 DPAPI 不可用（非 Windows），宁可留明文也不能把用户填的 Key 弄丢
        payload[_PLAIN_FIELD] = key
    try:
        CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except OSError:
        pass


def api_key(data: dict | None = None) -> str:
    """优先级：环境变量 > DPAPI 密文 > 旧明文。环境变量适合临时用、不落盘。"""
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env
    data = _read_file() if data is None else data
    saved = secret.unprotect(str(data.get(_ENC_FIELD) or ""))
    if saved:
        return saved
    return str(data.get(_PLAIN_FIELD) or "").strip()
