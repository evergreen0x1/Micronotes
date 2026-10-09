"""Micronotes entry point: `python micronotes.py`."""
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import __version__
from app.theme import resource_dir
from app.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Micronotes")
    app.setApplicationDisplayName("Micronotes")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    icon = resource_dir() / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
