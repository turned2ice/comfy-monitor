import psutil
from PySide6.QtCore import QSettings

ORG = "ComfyMonitor"
APP = "ComfyWidgetMuse2"

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8188,
    "system_drive": "C:\\",
    "extra_drive": "",
    "mode": "graph",
    "compact": False,
    "bg_color": "#00060F",
    "bg_opacity": 85,
    "master_opacity": 100,
    "text_color": "#CCCCCC",
    "accent_color": "#7DFF88",
    "off_color": "#FF5555",
    "border_gray": "#7B7B7B",
    "graph_label": "#C7C7C7",
    "graph_vram": "#4DA6FF",
    "graph_ram": "#FF56F9",
    "graph_drive": "#7DFF88",
}

COLOR_KEYS = (
    "bg_color", "text_color", "accent_color", "off_color", "border_gray",
    "graph_label", "graph_vram", "graph_ram", "graph_drive",
)
OPACITY_KEYS = ("bg_opacity", "master_opacity")


def _drives():
    try:
        return [p.device for p in psutil.disk_partitions() if p.device]
    except Exception:
        return ["C:\\"]


def default_extra():
    ds = _drives()
    for d in ds:
        if not d.upper().startswith("C:"):
            return d
    return ds[1] if len(ds) > 1 else ds[0] if ds else "C:\\"


class Config:
    def __init__(self):
        self.q = QSettings(ORG, APP)

    def get(self, key):
        if key == "extra_drive" and not self.q.value(key):
            return default_extra()
        v = self.q.value(key, DEFAULTS[key])
        if key == "port" or key in OPACITY_KEYS:
            try:
                return int(v)
            except (TypeError, ValueError):
                return DEFAULTS[key]
        if key == "compact":
            return str(v).lower() in ("1", "true") if isinstance(v, str) else bool(v)
        return v

    def set(self, key, value):
        self.q.setValue(key, value)

    def all(self):
        return {k: self.get(k) for k in DEFAULTS}
