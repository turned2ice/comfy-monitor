import os
import sys

from PySide6.QtWidgets import QApplication

from config import Config
from widget import ComfyWidget

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("ComfyMonitor")
    app.setApplicationName("ComfyWidgetMuse2")
    cfg = Config()
    w = ComfyWidget(cfg)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
