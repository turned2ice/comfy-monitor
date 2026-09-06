import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
    QVBoxLayout,
)

from color_popup import pick_color
from config import COLOR_KEYS, DEFAULTS

COLOR_LABELS = {
    "bg_color": "Background",
    "text_color": "Text",
    "accent_color": "Accent",
    "off_color": "Offline dot",
    "border_gray": "Borders",
    "graph_label": "Graph labels",
    "graph_vram": "VRAM graph",
    "graph_ram": "RAM graph",
    "graph_drive": "Drive graphs",
}

OPACITY_ROWS = (
    ("bg_opacity", "Background opacity", 20),
    ("master_opacity", "Overall opacity", 30),
)


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Settings")
        self.setFixedWidth(300)
        self._snapshot = {k: cfg.get(k)
                          for k in list(COLOR_KEYS) + [k for k, _, _ in OPACITY_ROWS]}
        try:
            drives = [p.device for p in psutil.disk_partitions() if p.device]
        except Exception:
            drives = ["C:\\"]
        if not drives:
            drives = ["C:\\"]
        cur = cfg.all()
        self.host = QLineEdit(cur["host"])
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(cur["port"]))
        self.sys = QComboBox()
        self.sys.addItems(drives)
        if cur["system_drive"] in drives:
            self.sys.setCurrentText(cur["system_drive"])
        self.ext = QComboBox()
        self.ext.addItems(drives)
        if cur["extra_drive"] in drives:
            self.ext.setCurrentText(cur["extra_drive"])
        form = QFormLayout()
        form.addRow("ComfyUI host", self.host)
        form.addRow("Port", self.port)
        form.addRow("System drive", self.sys)
        form.addRow("Extra drive", self.ext)
        for key, label in COLOR_LABELS.items():
            if key not in COLOR_KEYS:
                continue
            btn = QPushButton()
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _=False, k=key: self._pick(k))
            setattr(self, f"sw_{key}", btn)
            form.addRow(label, btn)
        self._paint_swatches()
        self._op_widgets = {}
        for key, label, lo in OPACITY_ROWS:
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, 100)
            slider.setValue(int(cfg.get(key)))
            lab = QLabel(f"{slider.value()}%")
            lab.setFixedWidth(42)
            slider.valueChanged.connect(
                lambda v, k=key, l=lab: self._set_opacity(k, v, l))
            self._op_widgets[key] = (slider, lab)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(lab)
            form.addRow(label, row)
        reset = QPushButton("Reset colors")
        reset.clicked.connect(self._reset_colors)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self._on_reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(reset)
        lay.addWidget(btns)

    def _retint(self):
        fn = getattr(self.parent(), "_apply_theme", None)
        if callable(fn):
            fn()

    def _paint_swatches(self):
        for key in COLOR_KEYS:
            btn = getattr(self, f"sw_{key}", None)
            if btn is None:
                continue
            col = str(self.cfg.get(key))
            btn.setStyleSheet(
                "QPushButton { background: %s;"
                " border: 1px solid #7B7B7B; border-radius: 4px; }" % col)

    def _pick(self, key):
        pick_color(QColor(str(self.cfg.get(key))),
                   lambda c, k=key: self._apply_color(k, c),
                   self, self.sender())

    def _apply_color(self, key, color):
        self.cfg.set(key, color.name().upper())
        self._paint_swatches()
        self._retint()

    def _set_opacity(self, key, value, lab):
        lab.setText(f"{value}%")
        self.cfg.set(key, int(value))
        self._retint()

    def _reset_colors(self):
        for key in list(COLOR_KEYS) + [k for k, _, _ in OPACITY_ROWS]:
            self.cfg.set(key, DEFAULTS[key])
        for key, (slider, lab) in self._op_widgets.items():
            slider.setValue(int(DEFAULTS[key]))
            lab.setText(f"{DEFAULTS[key]}%")
        self._paint_swatches()
        self._retint()

    def _on_reject(self):
        for k, v in self._snapshot.items():
            self.cfg.set(k, v)
        self._retint()
        self.reject()

    def values(self):
        return {
            "host": self.host.text().strip() or "127.0.0.1",
            "port": int(self.port.value()),
            "system_drive": self.sys.currentText(),
            "extra_drive": self.ext.currentText(),
        }
