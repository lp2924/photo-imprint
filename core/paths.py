"""运行目录。

打包成单文件 exe 后 __file__ 指向临时解压目录，配置写在那里会随退出丢失，
所以 frozen 状态下统一取 exe 所在目录。
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """只读资源目录（字体、翻译）。

    单文件 exe 的附带资源被解压到 sys._MEIPASS，和 exe 目录不是一回事。
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


APP_DIR = app_dir()
CONFIG_FILE = APP_DIR / "config.json"
CACHE_FILE = APP_DIR / "geo_cache.json"
TRANSLATIONS_DIR = resource_dir() / "assets" / "translations"
ICON_FILE = resource_dir() / "assets" / "app.ico"
SETTINGS_ICON_FILE = resource_dir() / "assets" / "settings.ico"
