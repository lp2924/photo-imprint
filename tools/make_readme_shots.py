"""生成 README 配图（docs/），只用脚本合成样片，不放任何真实照片。

    python tools/make_readme_shots.py

会依次产出：
    docs/screenshot-main.png      主界面（短写地名）
    docs/screenshot-full.png      全称写法
    docs/screenshot-settings.png  设置弹窗
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from ui.main_window import QSS, MainWindow

OUT = ROOT / "docs"
SAMPLES = ROOT / "samples" / "in"


def pump(app: QApplication, seconds: float = 2.0) -> None:
    for _ in range(int(seconds / 0.05)):
        app.processEvents()
        time.sleep(0.05)


def main() -> int:
    if not (SAMPLES / "01_横版_西湖.jpg").is_file():
        print("缺少合成样片，先跑：python tools/make_samples.py")
        return 1
    OUT.mkdir(exist_ok=True)

    app = QApplication([])
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.resize(1160, 900)
    # 用相对路径，截图里不至于显示到半截盘符路径
    window.set_input(Path("samples") / "in")
    window._show_path(window.output_edit, "samples\\out")
    window._output_auto = False

    # 固定成默认观感，避免受本机 config.json 影响
    window._set_style("B", silent=True)
    window._set_position("bottom-left", silent=True)
    window._set_color((255, 255, 255), auto=False, silent=True)
    window._set_outline_style("solid", silent=True)
    window._load_time_format("%Y.%m.%d %H:%M")
    window._set_place_slots(("province", "city", "district"), silent=True)
    window._set_place_style("short", silent=True)
    window.show()
    window.refresh_preview()
    pump(app, 3.0)
    window.grab().save(str(OUT / "screenshot-main.png"))

    window._set_place_style("full")
    pump(app, 2.5)
    window.grab().save(str(OUT / "screenshot-full.png"))

    # 设置弹窗是模态的，临时把 exec 换成 show 才能截到
    original_exec = QDialog.exec
    QDialog.exec = lambda self: (self.show(), self.raise_(), 0)[-1]
    try:
        window.open_settings()
        pump(app, 1.0)
        dialogs = [d for d in window.findChildren(QDialog) if d.isVisible()]
        if dialogs:
            dialog = dialogs[-1]
            for edit in dialog.findChildren(QLineEdit):
                edit.clear()  # 别把本机 Key 的掩码截进公开图里
            pump(app, 0.3)
            dialog.grab().save(str(OUT / "screenshot-settings.png"))
    finally:
        QDialog.exec = original_exec

    window.close()
    pump(app, 0.5)
    print("saved:", ", ".join(p.name for p in sorted(OUT.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
