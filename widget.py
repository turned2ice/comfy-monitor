import os
import time

from PySide6.QtCore import QBuffer, QIODevice, Qt, QSize, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImageReader, QMovie, QPainter, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from comfy_client import ComfyClient
from config import Config
from graphs import COLORS, GraphWidget
from settings_dialog import SettingsDialog
from stats_worker import StatsWorker
from tray import make_tray

HERE = os.path.dirname(os.path.abspath(__file__))
A = lambda n: os.path.join(HERE, "assets", n)

SAMPLER_NAMES = {
    "KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerDPMPP",
    "SamplerEuler", "SamplerLCM",
}

CORNER = 20


def is_sampler(class_type):
    if not class_type:
        return False
    if class_type in SAMPLER_NAMES:
        return True
    return "sampl" in class_type.lower()


class CapTopLabel(QLabel):
    """QLabel that paints all-caps text with cap-top at widget top,
    cancelling the font's built-in leading (QLabel always leaves
    ascent-capHeight px above caps, which reads as 'text sits lower')."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        fm = QFontMetrics(self.font())
        shift = max(0, fm.ascent() - fm.capHeight() - 2)
        p.drawText(self.rect().translated(0, -shift),
                   Qt.AlignLeft | Qt.AlignTop, self.text())


class ComfyWidget(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._labels = {}
        self._cur_node = ""
        self._sampler_on = False
        self._last_sample_node = ""
        self._last_sample_t = 0.0
        self._compact = cfg.get("compact")
        self._mode = cfg.get("mode") or "graph"
        self._drag = None
        self._rsz = None
        self._prompt_id = ""
        self._run_t0 = None
        self._last_v = 0
        self._seg_t0 = None
        self._sample_accum = 0.0
        self._done_border = False
        self._pre_border_geom = None
        self._movie_buf = None
        self._movie = None
        self._connected = False
        self._accent = QColor("#7DFF88")

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._root = QFrame(self)
        self._root.setObjectName("root")
        self._rlay = QVBoxLayout(self._root)
        self._rlay.setContentsMargins(15, 15, 15, 15)
        self._rlay.setSpacing(0)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.addWidget(self._root)

        # top bar (hidden in small version) — Penpot top_container: 210x33,
        # row space-between, all content top-aligned
        self.topbar = QWidget()
        self.topbar.setFixedHeight(33)
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.title = CapTopLabel("COMFY MONITOR")
        self.title.setFixedHeight(16)
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(5)
        left.addWidget(self.dot, alignment=Qt.AlignTop)
        left.addWidget(self.title, alignment=Qt.AlignTop)
        top.addLayout(left)
        top.setAlignment(left, Qt.AlignTop)
        top.addStretch(1)
        self.btn_toggle = self._btn(A("image.svg") if self._mode == "graph" else A("icon_graph.svg"), 19)
        self.btn_toggle.clicked.connect(self.toggle_mode)
        self.btn_toggle.setFixedSize(19, 19)
        self.btn_toggle.setStyleSheet(
            "QToolButton { background: transparent; border: none; padding: 0px; }")
        top.addWidget(self.btn_toggle, alignment=Qt.AlignTop)
        # window buttons sit 2px lower (Penpot buttons_container topPad 2)
        self.winbtns = QWidget()
        winlay = QHBoxLayout(self.winbtns)
        winlay.setContentsMargins(0, 2, 0, 0)
        winlay.setSpacing(10)
        self.btn_hide = self._btn(A("hide.svg"), 10)
        self.btn_hide.clicked.connect(self.hide_to_tray)
        self.btn_compact = self._btn(A("compact.svg"), 10)
        self.btn_compact.clicked.connect(self.toggle_compact)
        self.btn_close = self._btn(A("close.svg"), 10)
        self.btn_close.clicked.connect(QApplication.instance().quit)
        for b in (self.btn_hide, self.btn_compact, self.btn_close):
            winlay.addWidget(b)
        top.addWidget(self.winbtns, alignment=Qt.AlignTop)
        self._rlay.addWidget(self.topbar)

        # middle stacked
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        graphs_page = QWidget()
        grid = QGridLayout(graphs_page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)
        sys_d = str(cfg.get("system_drive"))
        ext_d = str(cfg.get("extra_drive"))
        self.g_vram = GraphWidget("vram", COLORS["vram"])
        self.g_sys = GraphWidget(sys_d, COLORS["drive"])
        self.g_ram = GraphWidget("ram", COLORS["ram"])
        self.g_ext = GraphWidget(ext_d, COLORS["drive"])
        grid.addWidget(self.g_vram, 0, 0)
        grid.addWidget(self.g_sys, 0, 1)
        grid.addWidget(self.g_ram, 1, 0)
        grid.addWidget(self.g_ext, 1, 1)
        self.preview = QLabel("waiting for render…")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setScaledContents(False)
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.KeepAspectRatio)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.errorOccurred.connect(self._on_video_error)
        self._video_buf = None
        self._preview_kind = "image"
        self.stack.addWidget(graphs_page)
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.video)
        self._rlay.addWidget(self.stack, 1)
        self.graphs_page = graphs_page

        # bottom status + bar
        bot = QHBoxLayout()
        bot.setContentsMargins(0, 6, 0, 0)
        self.status = QLabel("Idle")
        bot.addWidget(self.status, 1)
        self.btn_expand = self._btn(A("compact.svg"), 12)
        self.btn_expand.clicked.connect(self.toggle_compact)
        arrow = self.btn_expand.icon().pixmap(64, 64).toImage().flipped(
            Qt.Horizontal | Qt.Vertical)
        self.btn_expand.setIcon(QIcon(QPixmap.fromImage(arrow)))
        bot.addWidget(self.btn_expand, alignment=Qt.AlignVCenter)
        self._rlay.addLayout(bot)
        self.bar_bg = QFrame()
        self.bar_bg.setFixedHeight(7)
        self.bar_bg.setStyleSheet("background: rgba(255,255,255,0.12); border-radius: 3px;")
        bl = QHBoxLayout(self.bar_bg)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.bar = QFrame()
        self.bar.setFixedHeight(7)
        bl.addWidget(self.bar, alignment=Qt.AlignLeft)
        bl.addStretch(1)
        self._rlay.addWidget(self.bar_bg)
        self._bar_frac = 0.0

        self.tray = make_tray(
            self, A("tray.svg"), self.show_from_tray,
            self.open_settings, QApplication.instance().quit,
        )
        self.client = None
        self.worker = None
        self.setMouseTracking(True)
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
        self.apply_mode()
        self.apply_compact(first=True)
        self._apply_theme()
        self.start_backends()

    def _btn(self, icon, size):
        b = QToolButton()
        b.setIcon(QIcon(icon))
        b.setIconSize(QSize(size, size))
        b.setFixedSize(size + 8, size + 8)
        b.setStyleSheet("QToolButton { background: transparent; border: none; } QToolButton:hover { background: rgba(255,255,255,0.12); border-radius: 4px; }")
        b.setCursor(Qt.PointingHandCursor)
        return b

    # backends
    def start_backends(self):
        c = self.cfg.all()
        if self.client:
            try:
                self.client.stop()
            except Exception:
                pass
        self.client = ComfyClient(c["host"], int(c["port"]))
        self.client.connected.connect(self.on_conn)
        self.client.sampling.connect(self.on_sampling)
        self.client.executing.connect(self.on_executing)
        self.client.node_map.connect(self.on_nodemap)
        self.client.preview_image.connect(self.on_preview)
        self.client.preview_image_kj.connect(self.on_preview_kj)
        self.client.execution_success.connect(self.on_done)
        self.client.execution_error.connect(self.on_error)
        self.client.start()
        if self.worker:
            try:
                self.worker.stop()
            except Exception:
                pass
        self.worker = StatsWorker(
            lambda: (str(self.cfg.get("system_drive")), str(self.cfg.get("extra_drive")))
        )
        self.worker.stats.connect(self.on_stats)
        self.worker.start()

    def closeEvent(self, e):
        try:
            if self.client:
                self.client.stop()
            if self.worker:
                self.worker.stop()
        except Exception:
            pass
        e.accept()

    @staticmethod
    def _fmt_time(s):
        s = max(0, int(s))
        return f"{s // 60:02d}:{s % 60:02d}"

    @staticmethod
    def _rgba(hex_color, alpha_pct):
        try:
            h = str(hex_color).lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            a = max(0, min(100, int(alpha_pct))) / 100.0
        except (ValueError, TypeError, IndexError):
            r, g, b, a = 0, 6, 15, 0.85
        return f"rgba({r},{g},{b},{a:.2f})"

    def _apply_theme(self):
        c = self.cfg.all()
        text, accent = c["text_color"], c["accent_color"]
        gray, glabel = c["border_gray"], c["graph_label"]
        self._root.setStyleSheet(
            f"#root {{ background: {self._rgba(c['bg_color'], c['bg_opacity'])};"
            " border-radius: 15px; }"
            f"QLabel {{ color: {text}; background: transparent; }}"
        )
        self.title.setStyleSheet(f"color: {text}; font-size: 12px;")
        self.status.setStyleSheet(f"color: {text}; font-size: 14px;")
        self._paint_dot()
        self.bar.setStyleSheet(f"background: {accent}; border-radius: 3px;")
        self.preview.setStyleSheet(
            f"color: {gray}; font-size: 11px;"
            f" border: 1px solid {gray}; border-radius: 5px;"
        )
        self.video.setStyleSheet(
            f"background: transparent; border: 1px solid {gray}; border-radius: 5px;"
        )
        self._accent = QColor(accent)
        self.g_vram.set_color(c["graph_vram"])
        self.g_ram.set_color(c["graph_ram"])
        for g in (self.g_sys, self.g_ext):
            g.set_color(c["graph_drive"])
        for g in (self.g_vram, self.g_ram, self.g_sys, self.g_ext):
            g.set_border_color(gray)
            g.set_label_color(glabel)
        self.setWindowOpacity(c["master_opacity"] / 100.0)
        self.update()

    def _paint_dot(self):
        c = self.cfg.all()
        col = c["accent_color"] if self._connected else c["off_color"]
        self.dot.setStyleSheet(f"background: {col}; border-radius: 5px;")

    def _set_done_border(self, on):
        if on == self._done_border:
            return
        pad = 5
        if on:
            self._done_border = True
            self._pre_border_geom = (self.pos(), self.size())
            self._outer.setContentsMargins(pad, pad, pad, pad)
            self.resize(self.width() + pad * 2, self.height() + pad * 2)
            self.move(self.x() - pad, self.y() - pad)
        else:
            self._done_border = False
            self._outer.setContentsMargins(0, 0, 0, 0)
            if self._pre_border_geom is not None:
                pos, size = self._pre_border_geom
                self.resize(max(self.minimumWidth(), size.width()),
                            max(self.minimumHeight(), size.height()))
                self.move(pos)
                self._pre_border_geom = None
            else:
                self.resize(max(self.minimumWidth(), self.width() - pad * 2),
                            max(self.minimumHeight(), self.height() - pad * 2))
                self.move(self.x() + pad, self.y() + pad)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._done_border:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(self._accent)
            p.drawRoundedRect(self.rect(), 20, 20)

    def _clear_done_border(self):
        self._set_done_border(False)

    def enterEvent(self, e):
        super().enterEvent(e)
        self._clear_done_border()

    # slots
    def on_conn(self, ok):
        self._connected = bool(ok)
        self._paint_dot()

    def on_nodemap(self, m):
        self._labels = dict(m)
        if self._cur_node:
            self._sampler_on = is_sampler(self._labels.get(self._cur_node, ""))

    def on_executing(self, node, prompt_id):
        now = time.monotonic()
        if prompt_id and prompt_id != self._prompt_id:
            self._prompt_id = prompt_id
            self._run_t0 = None
            self._last_v = 0
            self._seg_t0 = None
            self._sample_accum = 0.0
            self._bar_frac = 0.0
            self._paint_bar()
            self._clear_done_border()
        elif self._seg_t0 is not None and node != self._cur_node:
            self._sample_accum += now - self._seg_t0
            self._seg_t0 = None
        self._cur_node = node
        if not node:
            self._sampler_on = False
            return
        self._sampler_on = is_sampler(self._labels.get(node, ""))
        label = self._labels.get(node, node)
        if self._sampler_on:
            self.status.setText(f"Sampling {label}…")
        else:
            self.status.setText(f"{label}…")

    def on_sampling(self, node, value, maximum):
        if maximum <= 1 and value <= 0:
            return
        self._last_sample_node = node
        now = time.monotonic()
        self._last_sample_t = now
        if self._run_t0 is None or value < self._last_v:
            self._run_t0 = now
        self._last_v = value
        if self._seg_t0 is None:
            self._seg_t0 = now
        if node and node in self._labels:
            self._sampler_on = is_sampler(self._labels[node])
        frac = (value / maximum) if maximum else 0.0
        self._bar_frac = max(0.0, min(1.0, frac))
        self._paint_bar()
        elapsed = now - self._run_t0
        total = elapsed / value * maximum if value > 0 and maximum else 0.0
        remaining = max(0.0, total - elapsed)
        self.status.setText(
            f"Sampling step {value}/{maximum} "
            f"[{self._fmt_time(elapsed)}/{self._fmt_time(remaining)}]"
        )

    def _preview_allowed(self):
        if self._sampler_on:
            return True
        if not self._labels and self._last_sample_node:
            if self._last_sample_node == self._cur_node:
                return (time.monotonic() - self._last_sample_t) < 2.0
        return False

    def on_preview(self, data):
        if not self._preview_allowed():
            return
        self._play_preview_bytes(bytes(data))

    def on_preview_kj(self, data, mime=""):
        if not self._cur_node and (time.monotonic() - self._last_sample_t) > 5.0:
            if not self._sampler_on:
                return
        if str(mime).startswith("video"):
            self._play_preview_video(bytes(data))
        else:
            self._play_preview_bytes(bytes(data))

    def _play_preview_video(self, data):
        if not data:
            return
        buf = QBuffer(self)
        buf.setData(data)
        if not buf.open(QIODevice.ReadOnly):
            buf.deleteLater()
            return
        old = self._video_buf
        self.player.stop()
        self.player.setSourceDevice(buf)
        self._video_buf = buf
        if old is not None:
            old.deleteLater()
        self._preview_kind = "video"
        if self._mode == "image":
            self.stack.setCurrentWidget(self.video)
        self.player.play()

    def _on_video_error(self):
        self._preview_kind = "image"
        if self._mode == "image":
            self.stack.setCurrentWidget(self.preview)

    def _play_preview_bytes(self, data):
        if not data:
            return
        self._preview_kind = "image"
        if self._mode == "image":
            self.stack.setCurrentWidget(self.preview)
        buf = QBuffer(self)
        buf.setData(data)
        if not buf.open(QIODevice.ReadOnly):
            buf.deleteLater()
            return
        if not QImageReader(buf).canRead():
            buf.deleteLater()
            return
        buf.seek(0)
        old_movie, old_buf = self._movie, self._movie_buf
        movie = QMovie(buf, parent=self)
        movie.frameChanged.connect(self._update_preview_pixmap)
        self._movie, self._movie_buf = movie, buf
        if old_movie is not None:
            old_movie.stop()
            old_movie.deleteLater()
        if old_buf is not None:
            old_buf.deleteLater()
        movie.start()
        self._update_preview_pixmap()

    def _update_preview_pixmap(self):
        movie = self._movie
        if movie is None:
            return
        pm = movie.currentPixmap()
        if pm.isNull():
            return
        t = self.preview.size()
        if t.width() < 2 or t.height() < 2:
            return
        self.preview.setPixmap(
            pm.scaled(t, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _close_segment(self):
        if self._seg_t0 is not None:
            self._sample_accum += time.monotonic() - self._seg_t0
            self._seg_t0 = None

    def on_done(self, pid):
        self._close_segment()
        self._bar_frac = 0.0
        self._paint_bar()
        self.status.setText(f"Done in {self._fmt_time(self._sample_accum)}")
        self._set_done_border(True)

    def on_error(self, msg):
        self._close_segment()
        self.status.setText(f"Error: {msg[:60]}")

    def on_stats(self, s):
        self.g_vram.push(s["vram"], f'{s.get("vram_used_mb", 0) / 1024:.1f}GB')
        self.g_ram.push(s["ram"], f'{s.get("ram_used_mb", 0) / 1024:.1f}GB')
        sd, ed = s.get("sys_drive", ""), s.get("ext_drive", "")
        if sd != self.g_sys._title:
            self.g_sys.set_title(sd)
        if ed != self.g_ext._title:
            self.g_ext.set_title(ed)
        self.g_sys.push(s["sys"], f'{s.get("sys_mbs", 0):.0f}MB/s')
        self.g_ext.push(s["ext"], f'{s.get("ext_mbs", 0):.0f}MB/s')

    # ui actions
    def _paint_bar(self):
        w = max(0, int(self.bar_bg.width() * self._bar_frac))
        self.bar.setFixedWidth(w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._paint_bar()
        self._update_preview_pixmap()
        QTimer.singleShot(0, self._update_preview_pixmap)

    def toggle_mode(self):
        self._mode = "image" if self._mode == "graph" else "graph"
        self.cfg.set("mode", self._mode)
        self.apply_mode()

    def apply_mode(self):
        if self._mode == "graph":
            self.stack.setCurrentWidget(self.graphs_page)
            self.btn_toggle.setIcon(QIcon(A("image.svg")))
        else:
            self.stack.setCurrentWidget(
                self.video if self._preview_kind == "video" else self.preview)
            self.btn_toggle.setIcon(QIcon(A("icon_graph.svg")))
            QTimer.singleShot(0, self._update_preview_pixmap)

    def toggle_compact(self):
        self._compact = not self._compact
        self.cfg.set("compact", self._compact)
        self.apply_compact()

    def apply_compact(self, first=False):
        if self._compact:
            if not first:
                self._reg_size = self.size()
            self.topbar.hide()
            self.stack.hide()
            self.btn_expand.show()
            self._rlay.setContentsMargins(15, 9, 15, 15)
            self.setMinimumSize(200, 56)
            self.resize(270 if first else self.width(), 60)
        else:
            self.topbar.show()
            self.stack.show()
            self.btn_expand.hide()
            self._rlay.setContentsMargins(15, 15, 15, 15)
            self.setMinimumSize(200, 140)
            if first:
                self.resize(270, 180)
            else:
                rs = getattr(self, "_reg_size", None)
                self.resize(self.width(), rs.height() if rs else 180)
        self._paint_bar()

    def hide_to_tray(self):
        self.hide()

    def show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def open_settings(self):
        before = {k: self.cfg.get(k)
                  for k in ("host", "port", "system_drive", "extra_drive")}
        d = SettingsDialog(self.cfg, self)
        if d.exec():
            for k, v in d.values().items():
                self.cfg.set(k, v)
            after = {k: self.cfg.get(k) for k in before}
            if after != before:
                self.start_backends()

    # drag anywhere + resize by bottom-right corner
    def _in_corner(self, pos):
        return pos.x() >= self.width() - CORNER and pos.y() >= self.height() - CORNER

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p = e.position().toPoint()
            if self._in_corner(p):
                self._rsz = (e.globalPosition().toPoint(), self.size())
            else:
                self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._rsz and e.buttons() & Qt.LeftButton:
            delta = e.globalPosition().toPoint() - self._rsz[0]
            w = max(self.minimumWidth(), self._rsz[1].width() + delta.x())
            h = max(self.minimumHeight(), self._rsz[1].height() + delta.y())
            self.resize(w, h)
        elif self._drag and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        elif not e.buttons():
            self.setCursor(Qt.SizeFDiagCursor if self._in_corner(e.position().toPoint())
                           else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self._rsz = None
