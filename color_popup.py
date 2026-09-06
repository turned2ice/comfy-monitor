from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout,
)

class ColorPopup(QFrame):
    """Wide HSV slider popup with hex + eyedropper and the native dialog
    as a fallback. Edits apply live through on_change; closing keeps the
    last value (Settings Cancel still rolls everything back via snapshot)."""

    def __init__(self, initial, on_change, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self._on_change = on_change
        self._color = QColor(initial) if QColor(initial).isValid() else QColor("#FFFFFF")
        self._picking = False
        self.setFixedWidth(236)
        self.setStyleSheet(
            "ColorPopup { background: #1E1E1E; border: 1px solid #3E3E42; border-radius: 8px; }"
            "QLabel { color: #CCCCCC; font-size: 11px; background: transparent; border: none; }"
            "QSlider::groove:horizontal { height: 14px; background: #2D2D30; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: #4DA6FF; border-radius: 7px; }"
            "QSlider::handle:horizontal { width: 20px; height: 20px;"
            " background: #CCCCCC; border: 1px solid #3E3E42; border-radius: 10px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._sliders = {}
        for key, lo, hi in (("h", 0, 359), ("s", 0, 100), ("v", 0, 100)):
            lab = QLabel(key.upper())
            lab.setFixedWidth(12)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setMinimumHeight(20)
            sl.valueChanged.connect(lambda _=None, k=key: self._from_sliders(k))
            self._sliders[key] = sl
            row = QHBoxLayout()
            row.addWidget(lab)
            row.addWidget(sl, 1)
            lay.addLayout(row)

        bottom = QHBoxLayout()
        self._preview = QLabel()
        self._preview.setFixedSize(30, 22)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.editingFinished.connect(self._from_hex)
        eye = QPushButton("⌖")
        eye.setFixedSize(30, 22)
        eye.setToolTip("Pick from screen")
        eye.clicked.connect(self._start_eye)
        more = QPushButton("More…")
        more.clicked.connect(self._native)
        bottom.addWidget(self._preview)
        bottom.addWidget(self.hex, 1)
        bottom.addWidget(eye)
        bottom.addWidget(more)
        lay.addLayout(bottom)

        self._sync_widgets()

    def show_at(self, widget):
        self.adjustSize()
        pos = QCursor.pos() - QPoint(self.width() // 2, 12)
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None and widget is not None:
            screen = QApplication.screenAt(
                widget.mapToGlobal(QPoint(0, widget.height())))
        if screen is not None:
            geo = screen.availableGeometry()
            pos.setX(min(max(pos.x(), geo.left()),
                         max(geo.left(), geo.right() - self.width())))
            pos.setY(min(max(pos.y(), geo.top()),
                         max(geo.top(), geo.bottom() - self.height())))
        self.move(pos)
        self.show()

    def closeEvent(self, e):
        self._stop_eye()
        super().closeEvent(e)

    # values <-> widgets
    def _set(self, color):
        if not color.isValid():
            return
        self._color = color
        self._sync_widgets()
        self._on_change(color)

    def _sync_widgets(self):
        h = self._color.hsvHue()
        for key, sl in self._sliders.items():
            sl.blockSignals(True)
        self._sliders["h"].setValue(h if h >= 0 else 0)
        self._sliders["s"].setValue(round(self._color.hsvSaturation() * 100 / 255))
        self._sliders["v"].setValue(round(self._color.value() * 100 / 255))
        for sl in self._sliders.values():
            sl.blockSignals(False)
        self.hex.blockSignals(True)
        self.hex.setText(self._color.name().upper())
        self.hex.blockSignals(False)
        self._preview.setStyleSheet(
            "QLabel { background: %s; border: 1px solid #3E3E42; border-radius: 4px; }"
            % self._color.name())

    def _from_sliders(self, changed):
        h = self._sliders["h"].value()
        s = round(self._sliders["s"].value() * 255 / 100)
        v = round(self._sliders["v"].value() * 255 / 100)
        if changed == "h" and s == 0 and v == 0:
            v = 255
        self._set(QColor.fromHsv(h, s, v))

    def _from_hex(self):
        text = self.hex.text().strip().lstrip("#")
        color = QColor("#" + text)
        if color.isValid() and len(text) == 6:
            self._set(color)
        else:
            self._sync_widgets()

    def _native(self):
        color = QColorDialog.getColor(self._color, self, "Custom color")
        if color.isValid():
            self._set(color)

    # eyedropper
    def _start_eye(self):
        if self._picking:
            return
        self._picking = True
        QApplication.setOverrideCursor(Qt.CrossCursor)
        QApplication.instance().installEventFilter(self)

    def _stop_eye(self):
        if not self._picking:
            return
        self._picking = False
        QApplication.restoreOverrideCursor()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, obj, ev):
        if not self._picking:
            return False
        if ev.type() == QEvent.MouseButtonPress:
            pos = QCursor.pos()
            screen = QApplication.screenAt(pos)
            if screen is not None:
                px = screen.grabWindow(0, pos.x(), pos.y(), 1, 1).toImage()
                if not px.isNull():
                    self._set(QColor(px.pixel(0, 0)))
            self._stop_eye()
            self.close()
            return True
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self._stop_eye()
            return True
        return False


def pick_color(initial, on_change, parent, anchor=None):
    pop = ColorPopup(initial, on_change, parent)
    pop.show_at(anchor)
    return pop
