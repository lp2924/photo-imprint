"""开发用：把主窗口渲染成图片，方便检查布局。不参与打包。

    python tools/shot_ui.py [输出路径]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from ui.main_window import QSS, MainWindow


def pump(app: QApplication, seconds: float) -> None:
    for _ in range(int(seconds / 0.05)):
        app.processEvents()
        time.sleep(0.05)


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.resize(1160, 840)
    window.show()
    pump(app, 2.0)

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "ui_window.png"
    if len(sys.argv) > 2:
        window.set_input(Path(sys.argv[2]))
        if len(sys.argv) > 3:
            window._show_path(window.output_edit, sys.argv[3])
            window.load_files()
        pump(app, 1.5)
    window.grab().save(str(out))
    sys.stdout.write(f"saved {out}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
