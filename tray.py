from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_tray(parent, icon_path, on_open, on_settings, on_close):
    tray = QSystemTrayIcon(QIcon(icon_path), parent)
    menu = QMenu()
    menu.addAction("Open", on_open)
    menu.addAction("Settings", on_settings)
    menu.addSeparator()
    menu.addAction("Close", on_close)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda r: on_open() if r == QSystemTrayIcon.DoubleClick else None
    )
    tray.setToolTip("COMFY MONITOR")
    tray.show()
    return tray
