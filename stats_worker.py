import subprocess
import time
import warnings

import psutil
from PySide6.QtCore import QThread, Signal

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import pynvml
        _NVML = True
    except Exception:
        _NVML = False


def _disk_key(drive):
    """Map 'C:\\' -> 'PhysicalDriveN' via Get-Partition (cached by caller)."""
    letter = (drive or "")[:1].upper()
    if not letter.isalpha():
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Partition -DriveLetter {letter} | Get-Disk |"
             " Select-Object -ExpandProperty Number)"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        return f"PhysicalDrive{int(out.split()[0])}"
    except Exception:
        return None


class StatsWorker(QThread):
    stats = Signal(dict)

    def __init__(self, get_drives, parent=None):
        super().__init__(parent)
        self._get_drives = get_drives
        self._running = True
        self._nv = False
        if _NVML:
            try:
                pynvml.nvmlInit()
                self._nv = pynvml.nvmlDeviceGetCount() > 0
            except Exception:
                self._nv = False
        self._disk_cache = {}
        self._peaks = {}
        self._prev_io = {}
        self._prev_t = 0.0

    def stop(self):
        self._running = False
        self.wait(2000)

    def _vram(self):
        if not self._nv:
            return 0.0, 0, 0
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            pct = m.used / m.total if m.total else 0.0
            return pct, m.used // (1024 * 1024), m.total // (1024 * 1024)
        except Exception:
            return 0.0, 0, 0

    def _disk_load(self, drive, cur, dt_s):
        """Disk load 0..1 = current throughput relative to session max."""
        if drive not in self._disk_cache:
            self._disk_cache[drive] = _disk_key(drive)
        key = self._disk_cache[drive]
        keys = [key] if key else [k for k in cur if k.lower().startswith("physicaldrive")]
        rate = 0.0
        for k in keys:
            if k in cur and k in self._prev_io and dt_s > 0:
                a, b = self._prev_io[k], cur[k]
                rate += max(0.0, (b.read_bytes - a.read_bytes)
                            + (b.write_bytes - a.write_bytes)) / dt_s
        peak = self._peaks.get(drive, 0.0)
        peak = max(rate, peak * 0.995)
        self._peaks[drive] = peak
        load = rate / peak if peak > 0 else 0.0
        return max(0.0, min(1.0, load)), rate

    def run(self):
        while self._running:
            sys_drive, extra_drive = self._get_drives()
            vram_pct, vram_used_mb, vram_total_mb = self._vram()
            try:
                vm = psutil.virtual_memory()
                ram_pct = vm.percent / 100.0
                ram_used_mb = vm.used // (1024 * 1024)
            except Exception:
                ram_pct = 0.0
                ram_used_mb = 0
            try:
                cur = psutil.disk_io_counters(perdisk=True) or {}
            except Exception:
                cur = {}
            now = time.monotonic()
            dt_s = now - self._prev_t if self._prev_t else 0.0
            sys_load, sys_rate = self._disk_load(sys_drive, cur, dt_s)
            ext_load, ext_rate = self._disk_load(extra_drive, cur, dt_s)
            self._prev_io = cur
            self._prev_t = now
            self.stats.emit({
                "vram": vram_pct, "vram_used_mb": vram_used_mb,
                "vram_total_mb": vram_total_mb,
                "ram": ram_pct, "ram_used_mb": ram_used_mb,
                "sys": sys_load, "sys_drive": sys_drive, "sys_mbs": sys_rate / 1e6,
                "ext": ext_load, "ext_drive": extra_drive, "ext_mbs": ext_rate / 1e6,
            })
            self.msleep(1000)
