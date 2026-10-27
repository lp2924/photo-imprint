"""Windows DPAPI：把敏感字符串加密成只有当前 Windows 账户能解开的密文。

高德 Key 明文写在 config.json 里，谁拷走这个文件（或整个程序目录）谁就能拿去刷配额。
DPAPI 加密后密文换机器、换账户都解不开，等于自动失效。
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _make_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    # 用 create_string_buffer(data, len) 不带结尾 0，避免把 \0 也算进明文
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _call(func, data: bytes) -> bytes | None:
    if not data:
        return None
    blob_in, _keep = _make_blob(data)
    blob_out = _Blob()
    ok = func(ctypes.byref(blob_in), None, None, None, None,
              _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _bind() -> None:
    if not available():
        return
    crypt32 = ctypes.windll.crypt32
    for name in ("CryptProtectData", "CryptUnprotectData"):
        func = getattr(crypt32, name)
        func.restype = wintypes.BOOL
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]


_bind()


def protect(text: str) -> str:
    """返回 base64 密文；失败返回空串，调用方据此决定要不要落盘。"""
    if not text or not available():
        return ""
    raw = _call(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))
    return base64.b64encode(raw).decode("ascii") if raw else ""


def unprotect(token: str) -> str:
    if not token or not available():
        return ""
    try:
        raw = base64.b64decode(token)
    except (ValueError, TypeError):
        return ""
    plain = _call(ctypes.windll.crypt32.CryptUnprotectData, raw)
    return plain.decode("utf-8") if plain else ""
