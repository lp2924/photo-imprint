"""主窗口：左侧参数卡片、右侧预览与队列。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QLibraryInfo, QRectF, QThread, QTimer, Qt, QTranslator, Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QColorDialog, QComboBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QVBoxLayout, QWidget,
)

from core import config_store, exif_reader, geo, layout, processor, watermark
from core import __version__ as APP_VERSION
from core.geo import GeoResolver
from core.paths import APP_DIR, CACHE_FILE, ICON_FILE, SETTINGS_ICON_FILE, TRANSLATIONS_DIR

def _icon_from(path: Path) -> QIcon:
    """图标文件缺失时给空图标，不影响启动。"""
    return QIcon(str(path)) if path.is_file() else QIcon()


def app_icon() -> QIcon:
    """窗口、任务栏共用的应用图标。"""
    return _icon_from(ICON_FILE)


def settings_icon() -> QIcon:
    """设置弹窗用齿轮：跟主窗口挂同一个图标会像是又开了一个主程序。"""
    return _icon_from(SETTINGS_ICON_FILE)


STYLE_ITEMS = [
    ("B", "半透明条"),
    ("A", "无底衬"),
    ("C", "拍立得"),
]

TIME_FORMATS = [
    ("2026.10.26 20:18", "%Y.%m.%d %H:%M"),
    ("2026-10-26 20:18", "%Y-%m-%d %H:%M"),
    ("2026年10月26日 20:18", "%Y年%m月%d日 %H:%M"),
    ("只有日期 2026.10.26", "%Y.%m.%d"),
    ("只有日期 2026年10月26日", "%Y年%m月%d日"),
    ("只有时间 20:18", "%H:%M"),
    ("不显示时间", ""),
]

# 12 个格位：11 个预设色 + 1 个自定义，正好排两行
COLOR_PRESETS = [
    ("白色", (255, 255, 255)),
    ("黑色", (26, 26, 26)),
    ("中灰", (110, 108, 102)),
    ("红色", (226, 75, 74)),
    ("橙色", (216, 90, 48)),
    ("暖黄", (250, 199, 117)),
    ("金色", (186, 117, 23)),
    ("绿色", (29, 158, 117)),
    ("青蓝", (24, 95, 165)),
    ("紫色", (83, 74, 183)),
    ("粉色", (212, 83, 126)),
]

DEFAULT_COLOR = (255, 255, 255)
DARK_COLOR = (58, 58, 56)
ACCENT = "#185FA5"
# 高德「我的应用」页：创建应用、看 Key 都在这里
AMAP_KEY_URL = "https://console.amap.com/dev/key/app"

# 描边色常用就这几个，其余交给取色器
OUTLINE_PRESETS = [
    ("白色", (255, 255, 255)),
    ("黑色", (26, 26, 26)),
    ("深灰", (90, 90, 88)),
    ("红色", (226, 75, 74)),
    ("蓝色", (24, 95, 165)),
]

QSS = f"""
QWidget {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 13px; color: #2C2C2A; }}
QWidget#root, QWidget#sidebar, QScrollArea#sidebarScroll {{ background: #F5F4F0; }}
QWidget#sidebarFooter {{ background: #EFEDE6; border-top: 1px solid #E1DFD7; }}
QScrollArea#sidebarScroll {{ border: none; }}
QFrame#card {{ background: #FFFFFF; border: 1px solid #E9E7DF; border-radius: 10px; }}
QFrame#previewBox {{ background: #EFEDE6; border: 1px solid #E4E2DA; border-radius: 12px; }}
QLabel#hint {{ color: #8A8880; font-size: 12px; }}
QLabel#sectionTitle {{ color: #2C2C2A; font-size: 12px; font-weight: 600; }}
QLabel#appName {{ font-size: 18px; font-weight: 600; color: #2C2C2A; }}
QLabel#preview {{ background: transparent; color: #8A8880; font-size: 12px; }}
QLineEdit, QComboBox {{
    background: #FFFFFF; border: 1px solid #E0DED6; border-radius: 7px;
    padding: 5px 8px; min-height: 17px;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: #FFFFFF; border: 1px solid #E0DED6; selection-background-color: #E6F1FB;
    selection-color: #0C447C; outline: none; padding: 4px;
}}
QPushButton {{ background: #FFFFFF; border: 1px solid #E0DED6; border-radius: 7px; padding: 5px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #B4B2A9; border-color: #EDEBE4; }}
QPushButton#primary {{
    background: {ACCENT}; color: #FFFFFF; border: none; border-radius: 8px;
    padding: 11px; font-size: 14px; font-weight: 500;
}}
QPushButton#primary:hover {{ background: #0C447C; color: #FFFFFF; }}
QPushButton#primary:disabled {{ background: #B5D4F4; color: #FFFFFF; }}
QPushButton#ghost {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 3px 6px; color: #8A8880; font-size: 12px;
}}
QPushButton#ghost:hover {{ background: #EAE8E0; color: #2C2C2A; border-color: transparent; }}
QPushButton#warn {{
    background: #FDF3E7; border: 1px solid #F0CE9B; border-radius: 7px;
    padding: 6px 8px; color: #8A5A17; font-size: 12px; text-align: left;
}}
QPushButton#warn:hover {{ background: #FCEAD6; border-color: #E5B872; }}
QPushButton#seg {{
    background: #FFFFFF; border: 1px solid #E0DED6; border-radius: 7px;
    padding: 7px 4px; color: #5F5E5A;
}}
QPushButton#seg:hover {{ background: #F3F2EC; color: #2C2C2A; }}
QPushButton#seg:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #FFFFFF; }}
QPushButton#seg:disabled {{ background: #F7F6F2; border-color: #EAE8E0; color: #B4B2AA; }}
QPushButton#chip {{
    background: #FFFFFF; border: 1px solid #E0DED6; border-radius: 6px;
    padding: 5px 2px; font-size: 12px; color: #5F5E5A;
}}
QPushButton#chip:hover {{ background: #F3F2EC; color: #2C2C2A; }}
QPushButton#chip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #FFFFFF; }}
QPushButton#chip:disabled {{ color: #B4B2AA; border-color: #EAE8E0; }}
QListWidget {{ background: #FFFFFF; border: 1px solid #E9E7DF; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 5px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #E6F1FB; color: #0C447C; }}
QProgressBar {{ background: #E8E6DF; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: #1D9E75; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: #E5E3DA; border-radius: 2px; }}
QSlider::groove:horizontal:disabled {{ background: #EFEDE7; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:disabled {{ background: #CFCDC5; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #D3D1C7; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #B4B2A9; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def _short_name(name: str, limit: int = 42) -> str:
    """微信保存的文件名特别长，列表里做中段省略，保留开头和扩展名。"""
    if len(name) <= limit:
        return name
    head = limit // 2
    return f"{name[:head]}…{name[-(limit - head):]}"


def to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    # tobytes 的缓冲区是临时的，必须 copy 才能跨线程安全使用
    buffer = img.tobytes("raw", "RGB")
    return QImage(buffer, img.width, img.height, img.width * 3,
                  QImage.Format_RGB888).copy()


class PositionPicker(QWidget):
    """九宫格示意图：点哪个格子水印就落在哪，比九个文字按钮直观也更省地方。"""

    changed = Signal(str)

    _PAD = 4
    _GAP = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(92, 58)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._value = "bottom-left"
        self._hover = ""
        self._sync_tip()

    # -- 对外 --
    def value(self) -> str:
        return self._value

    def setValue(self, key: str, emit: bool = False) -> None:
        valid = {k for k, _ in watermark.POSITIONS}
        self._value = key if key in valid else "bottom-left"
        self._sync_tip()
        self.update()
        if emit:
            self.changed.emit(self._value)

    # -- 内部 --
    def _sync_tip(self) -> None:
        label = dict(watermark.POSITIONS).get(self._value, "左下")
        self.setToolTip(f"水印位置：{label}")

    def _cell_rect(self, index: int) -> QRectF:
        pad, gap = self._PAD, self._GAP
        cell_w = (self.width() - pad * 2 - gap * 2) / 3
        cell_h = (self.height() - pad * 2 - gap * 2) / 3
        row, col = divmod(index, 3)
        return QRectF(pad + col * (cell_w + gap), pad + row * (cell_h + gap),
                      cell_w, cell_h)

    def _index_at(self, pos) -> int:
        for index in range(9):
            if self._cell_rect(index).contains(pos):
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position())
        key = watermark.POSITIONS[index][0] if index >= 0 else ""
        if key != self._hover:
            self._hover = key
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = ""
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            index = self._index_at(event.position())
            if index >= 0:
                self.setValue(watermark.POSITIONS[index][0], emit=True)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#E0DED6"), 1))
        painter.setBrush(QColor("#FBFAF6"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        for index, (key, _label) in enumerate(watermark.POSITIONS):
            cell = self._cell_rect(index)
            selected = key == self._value
            painter.setPen(Qt.NoPen)
            if selected:
                painter.setBrush(QColor(ACCENT))
            elif key == self._hover:
                painter.setBrush(QColor("#E6F1FB"))
            else:
                painter.setBrush(Qt.NoBrush)
            if selected or key == self._hover:
                painter.drawRoundedRect(cell, 4, 4)

            # 单条横杠代表那行字，格子位置本身就说明了落点
            bar_w, bar_h = cell.width() * 0.64, 4.0
            _v, horizontal = watermark.parse_position(key)
            top = cell.y() + (cell.height() - bar_h) / 2
            if horizontal == "left":
                x = cell.x() + (cell.width() - bar_w) / 2 - bar_w * 0.13
            elif horizontal == "right":
                x = cell.x() + (cell.width() + bar_w) / 2 - bar_w + bar_w * 0.13
            else:
                x = cell.x() + (cell.width() - bar_w) / 2
            painter.setBrush(QColor("#FFFFFF") if selected else QColor("#C6C4BB"))
            painter.drawRoundedRect(QRectF(x, top, bar_w, bar_h), 2, 2)
        painter.end()


class ColorSwatch(QWidget):
    """圆形色块，选中时套一圈描边，白球也能看清有没有被选中。"""

    picked = Signal(tuple)

    def __init__(self, color: tuple[int, int, int], name: str, size: int = 24,
                 parent=None):
        super().__init__(parent)
        self.color = tuple(color)
        self.setFixedSize(size, size)
        self.setToolTip(name)
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False
        self._hover = False

    def set_selected(self, flag: bool) -> None:
        if flag != self._selected:
            self._selected = flag
            self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.picked.emit(self.color)
        super().mousePressEvent(event)

    def _ring(self) -> tuple[QRectF, QRectF, QRectF]:
        """返回 (选中外圈, 外圈与色块之间的白隙, 色块) 三个同心圆。"""
        s = float(self.width())
        return (QRectF(0.5, 0.5, s - 1, s - 1),
                QRectF(s * 0.125, s * 0.125, s * 0.75, s * 0.75),
                QRectF(s * 0.21, s * 0.21, s * 0.58, s * 0.58))

    def _fill(self) -> None:
        pass

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        if not self.isEnabled():  # 描边关掉时整行压暗，比单纯 setEnabled 有反馈
            painter.setOpacity(0.35)
        outer, gap, inner = self._ring()
        s = float(self.width())
        if self._selected:
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(outer)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(gap)
        else:
            inner = QRectF(s * 0.145, s * 0.145, s * 0.71, s * 0.71)
        self._fill(painter, inner)
        if self._hover and not self._selected:
            painter.setPen(QPen(QColor(ACCENT), 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(outer.adjusted(1, 1, -1, -1))
        painter.end()


class PlainSwatch(ColorSwatch):
    def _fill(self, painter, inner) -> None:
        painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
        painter.setBrush(QColor(*self.color))
        painter.drawEllipse(inner)


class AutoSwatch(ColorSwatch):
    """「自动」：左黑右白，表示描边色跟着文字反色走。"""

    def __init__(self, size: int = 24, parent=None):
        super().__init__((255, 255, 255), "自动（黑字配白边 / 白字配黑边）", size, parent)

    def _fill(self, painter, inner) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(250, 250, 248))
        painter.drawEllipse(inner)
        painter.setBrush(QColor(36, 36, 34))
        painter.drawPie(inner, 90 * 16, 180 * 16)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(inner)


class CustomColorTile(ColorSwatch):
    """取色盘入口，画成彩虹圆环，一眼能看出是「更多颜色」。"""

    def __init__(self, size: int = 24, parent=None):
        super().__init__((255, 255, 255), "自定义颜色…", size, parent)

    def _fill(self, painter, inner) -> None:
        painter.setPen(Qt.NoPen)
        hues = ("#E24B4A", "#D85A30", "#FAC775", "#1D9E75", "#185FA5", "#534AB7")
        for index, hue in enumerate(hues):
            painter.setBrush(QColor(hue))
            painter.drawPie(inner, int(index * 60 * 16), int(60 * 16))
        c = inner.center()
        r = inner.width() * 0.22
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(c.x() - r, c.y() - r, r * 2, r * 2))


class PreviewTask(QThread):
    ready = Signal(object, str)

    def __init__(self, src: Path, cfg: processor.JobConfig,
                 resolver: GeoResolver, cap: int = 1600):
        super().__init__()
        self.src = src
        self.cfg = cfg
        self.resolver = resolver
        self.cap = cap

    def run(self) -> None:
        try:
            canvas, _meta, _place, _gps = processor.render(
                self.src, self.cfg, self.resolver, cap=self.cap
            )
            self.ready.emit(to_qimage(canvas), "")
        except Exception as exc:
            self.ready.emit(None, f"{type(exc).__name__}: {exc}")


class BatchTask(QThread):
    progress = Signal(int, int, object)
    finished_all = Signal(list)

    def __init__(self, files, cfg, resolver, root):
        super().__init__()
        self.files = files
        self.cfg = cfg
        self.resolver = resolver
        self.root = root

    def run(self) -> None:
        results = processor.process_batch(
            self.files, self.cfg, self.resolver, self.root,
            on_progress=lambda d, t, r: self.progress.emit(d, t, r),
            workers=4,
        )
        self.finished_all.emit(results)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"照片印迹 {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1160, 840)
        self.setMinimumSize(1000, 700)

        self.files: list[Path] = []
        self.input_dir: Path | None = None
        self._resolver = GeoResolver(cache_file=CACHE_FILE)
        self._style = "B"
        self._position = "bottom-left"
        self._color: tuple[int, int, int] = DEFAULT_COLOR
        self._color_auto = True  # 用户没手动挑过色时，允许跟着样式自动切换默认色
        self._outline_style = "solid"
        self._outline_color: tuple[int, int, int] | None = None   # None = 自动反色
        self._outline_width = 0.030
        self._api_key = ""
        self._key_locked = False
        self._pixmap: QPixmap | None = None
        self._preview_task: PreviewTask | None = None
        self._preview_seq = 0
        # 必须抱着正在跑的预览线程，提前丢引用会让 Qt 在析构时直接 abort
        self._live_tasks: set[PreviewTask] = set()
        self._batch_task: BatchTask | None = None
        self._result_items: dict[Path, QListWidgetItem] = {}
        self._output_auto = True  # 输出目录还没被手动选过时，跟着输入目录走
        self._loading = True  # 读取配置期间不触发预览，避免连打好几次地图接口

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self.refresh_preview)

        self._build_ui()
        self._load_state()
        self._loading = False
        self.refresh_preview()

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_main(), 1)

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 12, 10, 8)
        box.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("照片印迹")
        title.setObjectName("appName")
        head.addWidget(title)
        head.addStretch(1)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("ghost")
        self.settings_btn.setFixedWidth(50)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setToolTip("高德 Key 等一次性设置")
        self.settings_btn.clicked.connect(self.open_settings)
        head.addWidget(self.settings_btn)
        box.addLayout(head)

        sub = QLabel("批量给照片盖上拍摄时间和地点")
        sub.setObjectName("hint")
        box.addWidget(sub)
        box.addSpacing(2)

        box.addWidget(self._build_folder_card())
        box.addWidget(self._build_content_card())
        box.addWidget(self._build_style_card())
        box.addWidget(self._build_output_card())
        box.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("sidebarScroll")
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 按钮固定在底部，参数再多也不会把「开始处理」顶出屏幕
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        fbox = QVBoxLayout(footer)
        fbox.setContentsMargins(14, 8, 10, 10)
        fbox.setSpacing(6)

        # 没配 Key 时地点只能显示经纬度。放在底部按钮区，滚动参数区也不会把它挡住
        self.key_warn = QPushButton("未填高德 Key · 点此设置")
        self.key_warn.setObjectName("warn")
        self.key_warn.setCursor(Qt.PointingHandCursor)
        self.key_warn.clicked.connect(self.open_settings)
        self.key_warn.setVisible(False)
        fbox.addWidget(self.key_warn)

        self.start_btn = QPushButton("开始处理")
        self.start_btn.setObjectName("primary")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_batch)
        fbox.addWidget(self.start_btn)

        self.open_btn = QPushButton("打开输出目录")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_output)
        fbox.addWidget(self.open_btn)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(322)
        sbox = QVBoxLayout(sidebar)
        sbox.setContentsMargins(0, 0, 0, 0)
        sbox.setSpacing(0)
        sbox.addWidget(scroll, 1)
        sbox.addWidget(footer)
        return sidebar

    def _build_folder_card(self) -> QFrame:
        card = self._card()
        box = QVBoxLayout(card)
        box.setContentsMargins(11, 9, 11, 9)
        box.setSpacing(6)
        box.addWidget(self._section("文件夹"))

        self.input_edit = QLineEdit()
        self.input_edit.setReadOnly(True)
        self.input_edit.setPlaceholderText("选择存放原图的目录")
        box.addWidget(self._with_button(self.input_edit, "输入", self.pick_input))

        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("默认在原图目录下新建 out")
        box.addWidget(self._with_button(self.output_edit, "输出", self.pick_output))
        return card

    def _build_content_card(self) -> QFrame:
        card = self._card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(11, 9, 11, 9)
        outer.setSpacing(6)
        outer.addWidget(self._section("水印内容"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.time_combo = QComboBox()
        for text, fmt in TIME_FORMATS:
            self.time_combo.addItem(text, fmt)
        self.time_combo.addItem("自定义格式…", None)
        self.time_combo.currentIndexChanged.connect(self._on_time_preset)
        row = self._form_row(grid, 0, "时间格式", self.time_combo)

        # 只有选「自定义格式」时才出现，平时不占地方
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("如 %Y年%m月%d日，留空则不显示时间")
        self.time_edit.textChanged.connect(self._on_time_text)
        self.time_edit_wrap = QWidget()
        edit_box = QVBoxLayout(self.time_edit_wrap)
        edit_box.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.time_edit_wrap, row, 1)
        edit_box.addWidget(self.time_edit)
        self.time_edit_wrap.setVisible(False)
        row += 1

        self.place_mode = QComboBox()
        self.place_mode.addItem("读照片 GPS 自动查", "auto")
        self.place_mode.addItem("手动指定地点", "manual")
        self.place_mode.currentIndexChanged.connect(self._on_place_mode)
        row = self._form_row(grid, row, "位置来源", self.place_mode)

        self.place_edit = QLineEdit()
        self.place_edit.setPlaceholderText("如：浙江省杭州市西湖区")
        self.place_edit.textChanged.connect(self._debounce.start)
        row = self._form_row(grid, row, "地点", self.place_edit)

        # 地名层级自由组合：勾「省+区县」就是"甘肃 会宁"，勾「省+市」就是"甘肃 白银"
        self._place_slots = list(geo.DEFAULT_SLOTS)
        self.slot_chips = self._chips(geo.PLACE_SLOTS, self._place_slots)
        row = self._form_row(grid, row, "显示层级", self.slot_chips)

        # 同一批层级还能换写法：短写「甘肃 会宁」/ 全称「甘肃省白银市会宁县」
        self._place_style = geo.DEFAULT_STYLE
        self.place_style_seg = self._segment(geo.PLACE_STYLES, self._place_style,
                                             self._set_place_style)
        self.place_style_seg.setToolTip(
            "短写：去掉「省 / 市 / 区 / 县」后缀、空格分隔\n全称：照高德原样连写")
        row = self._form_row(grid, row, "写法", self.place_style_seg)

        self.place_hint = QLabel("选一张照片后显示")
        self.place_hint.setObjectName("hint")
        self._form_row(grid, row, "显示为", self.place_hint)
        return card

    def _build_style_card(self) -> QFrame:
        card = self._card()
        box = QVBoxLayout(card)
        box.setContentsMargins(11, 9, 11, 9)
        box.setSpacing(7)
        box.addWidget(self._section("水印外观"))

        self.style_seg = self._segment(STYLE_ITEMS, self._style, self._set_style)
        box.addWidget(self.style_seg)

        # 颜色与位置并排，省一整行高度
        side = QHBoxLayout()
        side.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(5)
        left.addWidget(self._label("文字颜色"))
        left.addWidget(self._build_swatches())
        left.addStretch(1)
        side.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(5)
        self._pos_title = self._label("文字位置")
        right.addWidget(self._pos_title)
        self._position_picker = PositionPicker()
        self._position_picker.changed.connect(lambda key: self._set_position(key))
        right.addWidget(self._position_picker)
        right.addStretch(1)
        side.addLayout(right)
        side.addStretch(1)

        box.addLayout(side)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(20, 55)
        self.size_slider.setValue(34)
        self.size_slider.valueChanged.connect(self._on_size_changed)
        self.size_value = QLabel("3.4%")
        row = self._form_row(grid, 0, "字号",
                             self._slider_widget(self.size_slider, self.size_value))

        self.outline_seg = self._segment(watermark.OUTLINE_STYLES, self._outline_style,
                                         self._set_outline_style)
        row = self._form_row(grid, row, "描边", self.outline_seg)

        self.outline_slider = QSlider(Qt.Horizontal)
        self.outline_slider.setRange(8, 80)
        self.outline_slider.setValue(int(self._outline_width * 1000))
        self.outline_slider.setToolTip("粗细是相对字号的比例：字号 40px 时 3% ≈ 1 像素")
        self.outline_slider.valueChanged.connect(self._on_outline_width)
        self.outline_value = QLabel("3.0%")
        row = self._form_row(grid, row, "粗细",
                             self._slider_widget(self.outline_slider, self.outline_value))

        self._outline_wrap = self._build_outline_swatches()
        self._outline_wrap.setToolTip("默认「自动」：白字配黑边、深色字配白边")
        self._form_row(grid, row, "描边色", self._outline_wrap)
        box.addLayout(grid)
        return card

    @staticmethod
    def _slider_widget(slider: QSlider, value: QLabel) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        value.setObjectName("hint")
        value.setFixedWidth(38)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(slider, 1)
        row.addWidget(value)
        return wrap

    def _build_output_card(self) -> QFrame:
        card = self._card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(11, 9, 11, 9)
        outer.setSpacing(6)
        outer.addWidget(self._section("输出"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.paper_combo = QComboBox()
        for name in layout.PAPER_PRESETS:
            self.paper_combo.addItem(name, name)
        self.paper_combo.currentIndexChanged.connect(self.refresh_preview)
        row = self._form_row(grid, 0, "纸型", self.paper_combo)

        self.fill_combo = QComboBox()
        self.fill_combo.addItem("补白不裁切", "pad")
        self.fill_combo.addItem("裁切铺满", "crop")
        self.fill_combo.setToolTip(
            "补白不裁切：整张照片全部保留，空白处补白，水印最安全\n"
            "裁切铺满：照片放大到铺满纸型，没有白边，但会裁掉长边两侧"
        )
        self.fill_combo.currentIndexChanged.connect(self.refresh_preview)
        self._form_row(grid, row, "摆法", self.fill_combo)
        return card

    def _build_main(self) -> QWidget:
        area = QWidget()
        area.setObjectName("root")
        box = QVBoxLayout(area)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(10)

        preview_box = QFrame()
        preview_box.setObjectName("previewBox")
        pbox = QVBoxLayout(preview_box)
        pbox.setContentsMargins(10, 10, 10, 10)

        self.preview = QLabel("左侧选择文件夹后，这里会显示加水印后的效果")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(240)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        pbox.addWidget(self.preview, 1)
        box.addWidget(preview_box, 1)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.count_label = QLabel("队列")
        self.count_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        head.addWidget(self.count_label)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        head.addWidget(self.progress, 1)
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("hint")
        head.addWidget(self.progress_text)
        box.addLayout(head)

        self.info_label = QLabel("")
        self.info_label.setObjectName("hint")
        # 长文本不参与撑宽，否则会把整个右栏顶变形
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        box.addWidget(self.info_label)

        self.file_list = QListWidget()
        self.file_list.setFixedHeight(140)
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        # 关闭横向滚动，长文件名才会按 ElideMiddle 省略而不是把列表撑出滚动条
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setTextElideMode(Qt.ElideMiddle)
        self.file_list.currentRowChanged.connect(self.refresh_preview)
        box.addWidget(self.file_list)
        return area

    # ---------- 小组件 ----------

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        return card

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        return label

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _form_row(self, grid: QGridLayout, row: int, text: str, widget) -> int:
        """标签在左、控件在右，比「标签单独一行」省掉一半纵向空间。"""
        label = self._label(text)
        label.setFixedWidth(62)
        grid.addWidget(label, row, 0, Qt.AlignVCenter)
        grid.addWidget(widget, row, 1)
        return row + 1

    def _with_button(self, edit: QLineEdit, text: str, slot) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        button = QPushButton(text)
        button.setFixedWidth(50)
        button.setToolTip(f"选择{text}文件夹")
        button.clicked.connect(slot)
        row.addWidget(button)
        return wrap

    def _segment(self, items, current: str, on_change) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        group = QButtonGroup(wrap)
        group.setExclusive(True)
        for key, text in items:
            btn = QPushButton(text)
            btn.setObjectName("seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("key", key)
            btn.setChecked(key == current)
            group.addButton(btn)
            row.addWidget(btn, 1)
        group.buttonClicked.connect(lambda btn: on_change(btn.property("key")))
        wrap._group = group  # 读当前值时要遍历按钮
        return wrap

    def _chips(self, items, current) -> QWidget:
        """多选小按钮，用来勾地名层级——勾哪几档就只显示哪几档。"""
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._slot_buttons: list[QPushButton] = []
        for key, text in items:
            btn = QPushButton(text)
            btn.setObjectName("chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("key", key)
            btn.setChecked(key in current)
            btn.clicked.connect(self._on_slot_toggled)
            row.addWidget(btn, 1)
            self._slot_buttons.append(btn)
        return wrap

    def _build_swatches(self) -> QWidget:
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        self._swatches: list[ColorSwatch] = []

        for index, (name, color) in enumerate(COLOR_PRESETS):
            swatch = PlainSwatch(color, name)
            swatch.picked.connect(lambda col: self._set_color(col))
            self._swatches.append(swatch)
            grid.addWidget(swatch, index // 6, index % 6)

        self._custom_tile = CustomColorTile()
        self._custom_tile.picked.connect(lambda _c: self.pick_color())
        grid.addWidget(self._custom_tile, len(COLOR_PRESETS) // 6,
                       len(COLOR_PRESETS) % 6)
        return wrap

    def _build_outline_swatches(self) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)

        self._auto_swatch = AutoSwatch(22)
        self._auto_swatch.picked.connect(lambda _c: self._set_outline_color(None))
        row.addWidget(self._auto_swatch)

        self._outline_swatches: list[ColorSwatch] = []
        for name, color in OUTLINE_PRESETS:
            swatch = PlainSwatch(color, name, 22)
            swatch.picked.connect(lambda col: self._set_outline_color(col))
            self._outline_swatches.append(swatch)
            row.addWidget(swatch)

        self._outline_custom = CustomColorTile(22)
        self._outline_custom.setToolTip("自定义描边色…")
        self._outline_custom.picked.connect(lambda _c: self.pick_outline_color())
        row.addWidget(self._outline_custom)
        row.addStretch(1)
        return wrap

    # ---------- 状态 ----------

    def _current_config(self, output_dir: Path | None = None) -> processor.JobConfig:
        out = output_dir or Path(self.output_edit.text() or ".")
        return processor.JobConfig(
            output_dir=out,
            style=self._style,
            paper=self.paper_combo.currentData(),
            fill_mode=self.fill_combo.currentData(),
            place_mode=self.place_mode.currentData(),
            manual_place=self.place_edit.text().strip(),
            place_slots=tuple(self._place_slots),
            place_style=self._place_style,
            date_format=self.time_edit.text().strip(),
            color=self._color,
            position=self._position,
            font_scale=self.size_slider.value() / 1000.0,
            outline_style=self._outline_style,
            outline_color=self._outline_color,
            outline_width=self._outline_width,
        )

    def _load_state(self) -> None:
        data = config_store.load_config()

        saved_input = data.get("input_dir")
        if saved_input:
            folder = Path(saved_input)
            if not folder.is_absolute():  # 旧配置里可能存的是相对路径
                folder = APP_DIR / folder
            if folder.is_dir():
                self.set_input(folder)
                if data.get("output_dir"):
                    self._show_path(self.output_edit, data["output_dir"])
                    self._output_auto = False

        for combo, key, default in (
            (self.paper_combo, "paper", layout.DEFAULT_PAPER),
            (self.fill_combo, "fill_mode", "pad"),
            (self.place_mode, "place_mode", "auto"),
        ):
            index = combo.findData(data.get(key, default))
            if index >= 0:
                combo.setCurrentIndex(index)

        # 旧配置里存的是档位名（street 之类），normalize_slots 会自动翻译成层级
        self._set_place_slots(data.get("place_slots", data.get("place_detail", "district")),
                              silent=True)
        self._set_place_style(data.get("place_style", geo.DEFAULT_STYLE), silent=True)

        self.place_edit.setText(data.get("place", ""))
        self._api_key = config_store.api_key(data)
        # 密文只对本机本账户有效，换机器/换账户后就是解不开的状态
        self._key_locked = not self._api_key and bool(data.get("api_key_enc"))
        self.key_warn.setVisible(not self._api_key)
        self.size_slider.setValue(int(data.get("font_scale", 0.034) * 1000))

        style = data.get("style", "B")
        self._set_style(style if style in ("A", "B", "C") else "B", silent=True)

        saved_color = data.get("color")
        if isinstance(saved_color, list) and len(saved_color) == 3:
            try:
                self._set_color(tuple(int(v) for v in saved_color), auto=False, silent=True)
            except (TypeError, ValueError):
                self._refresh_color_selection()
        else:
            self._refresh_color_selection()

        self._set_position(data.get("position", "bottom-left"), silent=True)
        self._load_outline(data)
        self._load_time_format(data.get("date_format", TIME_FORMATS[0][1]))
        self._on_place_mode()
        self._apply_key()

    def _load_outline(self, data: dict) -> None:
        valid = {key for key, _ in watermark.OUTLINE_STYLES}
        style = data.get("outline_style", "solid")
        self._set_outline_style(style if style in valid else "solid", silent=True)
        try:
            width = float(data.get("outline_width", 0.030))
        except (TypeError, ValueError):
            width = 0.030
        self.outline_slider.setValue(int(max(0.008, min(0.080, width)) * 1000))

        saved = data.get("outline_color")
        color = None
        if isinstance(saved, list) and len(saved) == 3:
            try:
                color = tuple(int(v) for v in saved)
            except (TypeError, ValueError):
                color = None
        self._set_outline_color(color, silent=True)

    def _load_time_format(self, fmt: str) -> None:
        index = self.time_combo.findData(fmt)
        if index >= 0:
            self.time_combo.setCurrentIndex(index)
            self.time_edit.setText(fmt)
            self.time_edit_wrap.setVisible(False)
        else:
            self.time_combo.setCurrentIndex(self.time_combo.count() - 1)
            self.time_edit.setText(fmt)
            self.time_edit_wrap.setVisible(True)

    def _save_state(self) -> None:
        data = {
            "input_dir": self.input_edit.text(),
            "output_dir": self.output_edit.text(),
            "style": self._style,
            "position": self._position,
            "paper": self.paper_combo.currentData(),
            "fill_mode": self.fill_combo.currentData(),
            "place_mode": self.place_mode.currentData(),
            "place": self.place_edit.text().strip(),
            "place_slots": list(self._place_slots),
            "place_style": self._place_style,
            "date_format": self.time_edit.text().strip(),
            "color": list(self._color),
            "api_key": self._api_key,  # save_config 会加密后再落盘
            "font_scale": self.size_slider.value() / 1000.0,
            "outline_style": self._outline_style,
            "outline_color": list(self._outline_color) if self._outline_color else None,
            "outline_width": self.outline_slider.value() / 1000.0,
        }
        config_store.save_config(data)

    def closeEvent(self, event) -> None:
        self._save_state()
        # 预览线程还在跑就直接析构 QThread 会让进程 abort，等它收尾
        for task in list(self._live_tasks):
            task.wait(2000)
        if self._batch_task and self._batch_task.isRunning():
            self._batch_task.wait(3000)
        super().closeEvent(event)

    # ---------- 交互 ----------

    def _on_slot_toggled(self) -> None:
        checked = {b.property("key") for b in self._slot_buttons if b.isChecked()}
        if not checked:
            # 一档都不勾地点就空了，至少留一档
            self.sender().setChecked(True)
            return
        self._place_slots = [key for key in geo.SLOT_KEYS if key in checked]
        self.refresh_preview()

    def _set_place_slots(self, slots, silent: bool = False) -> None:
        picked = geo.normalize_slots(slots)
        self._place_slots = list(picked)
        for button in self._slot_buttons:
            button.setChecked(button.property("key") in picked)
        if not silent:
            self.refresh_preview()

    def _set_place_style(self, key: str, silent: bool = False) -> None:
        self._place_style = key if key in geo.STYLE_KEYS else geo.DEFAULT_STYLE
        for button in self.place_style_seg._group.buttons():
            button.setChecked(button.property("key") == self._place_style)
        if not silent:
            self.refresh_preview()

    def _set_style(self, key: str, silent: bool = False) -> None:
        self._style = key
        for button in self.style_seg._group.buttons():
            button.setChecked(button.property("key") == key)
        # 白底样式配白字等于看不见，用户没手动挑过色就自动换成深灰
        if self._color_auto:
            self._color = DARK_COLOR if key == "C" else DEFAULT_COLOR
            self._refresh_color_selection()
        if not silent:
            self.refresh_preview()

    def _set_position(self, key: str, silent: bool = False) -> None:
        self._position = key
        self._position_picker.setValue(key)
        label = dict(watermark.POSITIONS).get(key, "左下")
        self._pos_title.setText(f"文字位置 · {label}")
        if not silent:
            self.refresh_preview()

    def _set_color(self, color: tuple[int, int, int], auto: bool = False,
                   silent: bool = False) -> None:
        self._color = tuple(color)
        if not auto:
            self._color_auto = False
        self._refresh_color_selection()
        if not silent:
            self.refresh_preview()

    def _refresh_color_selection(self) -> None:
        matched = False
        for swatch in self._swatches:
            hit = tuple(swatch.color) == tuple(self._color)
            matched = matched or hit
            swatch.set_selected(hit)
        # 手挑的颜色不在预设里时，让彩虹球亮着表示「当前用的是自定义色」
        self._custom_tile.set_selected(not matched)

    def pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(*self._color), self, "选择水印文字颜色",
            QColorDialog.DontUseNativeDialog,  # 原生对话框不吃 Qt 翻译，强制用自带的中文版
        )
        if chosen.isValid():
            self._set_color((chosen.red(), chosen.green(), chosen.blue()))

    # ---------- 描边 ----------

    def _set_outline_style(self, key: str, silent: bool = False) -> None:
        valid = {k for k, _ in watermark.OUTLINE_STYLES}
        self._outline_style = key if key in valid else "solid"
        for button in self.outline_seg._group.buttons():
            button.setChecked(button.property("key") == self._outline_style)
        on = self._outline_style != "none"
        self.outline_slider.setEnabled(on)
        self._outline_wrap.setEnabled(on)
        if not silent:
            self.refresh_preview()

    def _set_outline_color(self, color: tuple[int, int, int] | None,
                           silent: bool = False) -> None:
        self._outline_color = tuple(color) if color else None
        self._refresh_outline_selection()
        if not silent:
            self.refresh_preview()

    def _refresh_outline_selection(self) -> None:
        matched = False
        for swatch in self._outline_swatches:
            hit = (self._outline_color is not None
                   and tuple(swatch.color) == tuple(self._outline_color))
            matched = matched or hit
            swatch.set_selected(hit)
        self._auto_swatch.set_selected(self._outline_color is None)
        self._outline_custom.set_selected(self._outline_color is not None and not matched)

    def pick_outline_color(self) -> None:
        base = self._outline_color or watermark._auto_outline_color(self._color)
        chosen = QColorDialog.getColor(QColor(*base), self, "选择描边颜色",
                                       QColorDialog.DontUseNativeDialog)
        if chosen.isValid():
            self._set_outline_color((chosen.red(), chosen.green(), chosen.blue()))

    def _on_outline_width(self, value: int) -> None:
        self._outline_width = value / 1000.0
        self.outline_value.setText(f"{value / 10:.1f}%")
        self._debounce.start()

    def _on_time_preset(self) -> None:
        fmt = self.time_combo.currentData()
        custom = fmt is None
        self.time_edit_wrap.setVisible(custom)
        if not custom:
            self.time_edit.setText(fmt)
        self._debounce.start()

    def _on_time_text(self) -> None:
        self._debounce.start()

    def _on_size_changed(self, value: int) -> None:
        self.size_value.setText(f"{value / 10:.1f}%")
        self._debounce.start()

    def _on_place_mode(self) -> None:
        manual = self.place_mode.currentData() == "manual"
        self.place_edit.setPlaceholderText(
            "整批统一使用这个地点" if manual else "无 GPS 的照片用这个地点兜底")
        # 手动模式的地点是自己敲的整串文字，层级勾选和写法对它都没有意义
        self.slot_chips.setEnabled(not manual)
        self.place_style_seg.setEnabled(not manual)
        self.refresh_preview()

    def _apply_key(self) -> None:
        self._resolver.api_key = self._api_key

    def open_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("设置")
        dialog.setWindowIcon(settings_icon())
        dialog.setMinimumWidth(440)
        box = QVBoxLayout(dialog)
        box.setContentsMargins(18, 16, 18, 14)
        box.setSpacing(8)

        box.addWidget(self._section("高德地图 Key"))
        tip = QLabel(
            "路径：高德开放平台 → 应用管理 → 我的应用\n"
            "添加 Key 时「服务平台」要选 Web服务\n"
            "不填也能用，只是水印上会显示经纬度而不是地名。"
        )
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        box.addWidget(tip)

        # 直接给个能点的入口，省得用户照着文字去翻控制台
        link = QLabel(f'<a href="{AMAP_KEY_URL}" style="color:{ACCENT}; text-decoration:none;">'
                      "打开高德控制台申请 Key ↗</a>")
        link.setTextFormat(Qt.RichText)
        link.setOpenExternalLinks(True)  # 交给系统默认浏览器
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(AMAP_KEY_URL)
        box.addWidget(link)

        edit = QLineEdit(self._api_key)
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText("留空则显示经纬度")
        box.addWidget(edit)

        if self._key_locked:
            locked = QLabel("配置里有一份 Key，但在本机解不开（换了电脑或 Windows 账户），重新填一次即可。")
            locked.setObjectName("hint")
            locked.setWordWrap(True)
            box.addWidget(locked)

        safe = QLabel("Key 用当前 Windows 账户加密后存进 config.json，拷给别人也用不了。")
        safe.setObjectName("hint")
        safe.setWordWrap(True)
        box.addWidget(safe)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dialog.reject)
        row.addWidget(cancel)
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.setFixedWidth(88)
        ok.clicked.connect(dialog.accept)
        row.addWidget(ok)
        box.addLayout(row)

        if dialog.exec() == QDialog.Accepted:
            self._api_key = edit.text().strip()
            self._key_locked = False
            self.key_warn.setVisible(not self._api_key)
            self._apply_key()
            self._save_state()
            self.refresh_preview()

    def pick_input(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择原图文件夹")
        if folder:
            self.set_input(Path(folder))

    def pick_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self._show_path(self.output_edit, folder)
            self._output_auto = False
            self.open_btn.setEnabled(True)
            # 输出目录变了，待处理清单要重扫（输出目录本身会被排除）
            if self.input_dir:
                self.load_files()

    @staticmethod
    def _show_path(edit: QLineEdit, path: str) -> None:
        """路径太长时把光标放到末尾，让输入框露出文件夹名而不是盘符。"""
        edit.setText(path)
        edit.setCursorPosition(len(path))

    def set_input(self, folder: Path) -> None:
        self._show_path(self.input_edit, str(folder))
        self.input_dir = folder
        # 输出目录还是自动默认值时跟着输入走，用户手动选过就不再覆盖
        if self._output_auto:
            self._show_path(self.output_edit, str(folder / "out"))
        self.load_files()

    def load_files(self) -> None:
        self.file_list.clear()
        self._result_items.clear()
        output = self.output_edit.text().strip()
        exclude = [Path(output)] if output else []
        scanned = processor.collect_files(self.input_dir) if self.input_dir else []
        self.files = (processor.collect_files(self.input_dir, exclude=exclude)
                      if self.input_dir else [])

        for path in self.files:
            item = QListWidgetItem(_short_name(path.name))
            item.setToolTip(str(path))
            self.file_list.addItem(item)
            self._result_items[path] = item

        count = len(self.files)
        skipped = len(scanned) - count
        label = f"队列 · {count} 张"
        if skipped > 0:
            label += f"　·　跳过输出目录 {skipped} 张"
        self.count_label.setText(label)
        self.start_btn.setEnabled(count > 0)
        self.open_btn.setEnabled(bool(output))
        self.progress.setRange(0, max(1, count))
        self.progress.setValue(0)
        self.progress_text.setText("")
        if count:
            self.file_list.setCurrentRow(0)
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("这个目录里没找到 jpg / heic / png 照片")

    def open_output(self) -> None:
        folder = Path(self.output_edit.text().strip())
        if folder.is_dir():
            QApplication.openUrl(folder.as_uri())

    # ---------- 预览 ----------

    def refresh_preview(self) -> None:
        if self._loading:
            return
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self.files):
            return
        src = self.files[row]
        self._apply_key()
        cfg = self._current_config()

        self._preview_seq += 1
        seq = self._preview_seq
        self.preview.setText("正在生成预览…")

        task = PreviewTask(src, cfg, self._resolver)
        task.ready.connect(lambda image, error, s=seq: self._on_preview_ready(image, error, s))
        task.finished.connect(lambda t=task: self._live_tasks.discard(t))
        self._live_tasks.add(task)
        self._preview_task = task
        task.start()

    def _on_preview_ready(self, image, error: str, seq: int = 0) -> None:
        if seq != self._preview_seq:
            return  # 已有更新的预览请求，丢弃过期结果
        if error:
            self.preview.setText(f"预览失败：{error}")
            self._pixmap = None
            return
        self._pixmap = QPixmap.fromImage(image)
        self._update_scaled_preview()

        row = self.file_list.currentRow()
        if 0 <= row < len(self.files):
            try:
                cfg = self._current_config()
                meta = exif_reader.read_meta(self.files[row])
                place, _from_gps = processor.resolve_place(meta, cfg, self._resolver)
                when = meta.taken_at.strftime("%Y-%m-%d %H:%M:%S") if meta.taken_at else "无时间"
                source = {"exif": "EXIF", "file": "文件时间"}.get(meta.taken_source, "未知")
                gps = f"{meta.gps[0]:.4f}, {meta.gps[1]:.4f}" if meta.gps else "无"
                name = self.files[row].name
                if len(name) > 22:
                    name = name[:20] + "…"
                self.info_label.setText(
                    f"{name}　·　{when}（{source}）　·　GPS {gps}　·　地点 {place or '未识别'}"
                )
                self.place_hint.setText(place or "未识别 · 可在上面手动填地点")
            except Exception:
                self.info_label.setText(self.files[row].name)

    def _update_scaled_preview(self) -> None:
        if not self._pixmap:
            return
        area = self.preview.size()
        scaled = self._pixmap.scaled(max(1, area.width() - 16), max(1, area.height() - 16),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled_preview()

    # ---------- 处理 ----------

    def start_batch(self) -> None:
        if not self.files:
            return
        output = Path(self.output_edit.text().strip())
        self._save_state()
        self._apply_key()
        cfg = self._current_config(output)

        self.start_btn.setEnabled(False)
        self.start_btn.setText("处理中…")
        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self.progress_text.setText(f"0 / {len(self.files)}")

        for item in self._result_items.values():
            item.setText(item.text().split("　·　")[0])

        self._batch_task = BatchTask(self.files, cfg, self._resolver, self.input_dir)
        self._batch_task.progress.connect(self._on_batch_progress)
        self._batch_task.finished_all.connect(self._on_batch_done)
        self._batch_task.start()

    def _on_batch_progress(self, done: int, total: int, result) -> None:
        self.progress.setValue(done)
        self.progress_text.setText(f"{done} / {total}")
        item = self._result_items.get(result.src)
        if item:
            base = item.text().split("　·　")[0]
            if result.ok:
                item.setText(f"{base}　·　完成")
                item.setToolTip(str(result.dst))
            else:
                item.setText(f"{base}　·　失败")
                item.setToolTip(result.error)

    def _on_batch_done(self, results: list) -> None:
        ok = sum(1 for r in results if r.ok)
        failed = [r for r in results if not r.ok]
        self.start_btn.setEnabled(True)
        self.start_btn.setText("开始处理")
        self.open_btn.setEnabled(True)
        self.progress_text.setText(f"完成 {ok} / {len(results)}")
        self.count_label.setText(f"队列 · {len(self.files)} 张　完成 {ok}")

        if failed:
            detail = "\n".join(f"{r.src.name}: {r.error}" for r in failed[:6])
            self.info_label.setText(f"{len(failed)} 张失败：\n{detail}")
        else:
            self.info_label.setText(f"全部完成，已输出到 {self.output_edit.text()}")


def _install_translator(app: QApplication) -> bool:
    """让取色器、文件对话框这些 Qt 内置控件也显示中文。

    先找随程序走的 assets/translations（打包后也能用），再退回 PySide6 自带的翻译目录。
    """
    translator = QTranslator(app)
    for folder in (TRANSLATIONS_DIR, Path(QLibraryInfo.path(QLibraryInfo.TranslationsPath))):
        if folder.is_dir() and translator.load("qtbase_zh_CN", str(folder)):
            app.installTranslator(translator)
            return True
    return False


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("照片印迹")
    app.setWindowIcon(app_icon())  # 弹窗没单独设图标时也走这个
    _install_translator(app)

    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()
    return app.exec()
