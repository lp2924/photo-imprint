"""开发用：截取颜色选择器，确认内置控件也是中文。不参与打包。

    python tools/shot_dialog.py [输出路径]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from ui.main_window import QSS


def main() -> int:
    app = QApplication([])
    translator = QTranslator(app)
    loaded = translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    if loaded:
        app.installTranslator(translator)
    app.setStyleSheet(QSS)

    dialog = QColorDialog(QColor(226, 75, 74))
    dialog.setWindowTitle("选择水印文字颜色")
    dialog.setOption(QColorDialog.DontUseNativeDialog, True)
    dialog.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.05)

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "dialog_color.png"
    dialog.grab().save(str(out))
    sys.stdout.write(f"translator_loaded={loaded} saved={out}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
