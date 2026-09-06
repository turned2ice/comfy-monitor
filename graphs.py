from collections import deque
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

COLORS = {
    "vram": "#4DA6FF",
    "ram": "#FF56F9",
    "drive": "#7DFF88",
}


class GraphWidget(QFrame):
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self._hist = deque([0.0] * 60, maxlen=60)
        self._color = QColor(color)
        self._title = title
        self._sub = ""
        self.setStyleSheet(
            "GraphWidget { background: transparent; border: 1px solid #7B7B7B; border-radius: 5px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)
        self.lbl = QLabel(title)
        self.lbl.setStyleSheet("color: #C7C7C7; font-size: 10px; background: transparent; border: none;")
        self.lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addStretch(1)
        lay.addWidget(self.lbl)
        self.setMinimumSize(80, 30)

    def set_title(self, t):
        self._title = t

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_border_color(self, color):
        self.setStyleSheet(
            f"GraphWidget {{ background: transparent; border: 1px solid {color}; border-radius: 5px; }}"
        )

    def set_label_color(self, color):
        self.lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent; border: none;")

    def push(self, pct, sub=""):
        self._hist.append(max(0.0, min(1.0, pct)))
        self._sub = sub
        t = self._title if not sub else f"{self._title} {sub}"
        if t != self.lbl.text():
            self.lbl.setText(t)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        hist = list(self._hist)
        n = len(hist)
        if n < 2:
            return
        top = r.top() + 2
        base = r.bottom() - 14
        if base <= top:
            return
        pts = [
            (r.left() + i * r.width() / (n - 1), base - v * (base - top))
            for i, v in enumerate(hist)
        ]
        fill_path = QPainterPath()
        fill_path.moveTo(pts[0][0], base)
        for x, y in pts:
            fill_path.lineTo(x, y)
        fill_path.lineTo(pts[-1][0], base)
        fill_path.closeSubpath()
        grad = QLinearGradient(0, top, 0, base)
        c = self._color
        grad.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 160))
        grad.setColorAt(1, QColor(0x23, 0x28, 0x30, 255))
        p.fillPath(fill_path, grad)
        line = QPainterPath()
        line.moveTo(*pts[0])
        for x, y in pts[1:]:
            line.lineTo(x, y)
        p.setPen(QPen(self._color, 1))
        p.drawPath(line)
