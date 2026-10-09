"""Palettes, fonts and the application stylesheet."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from .formats import COLOR_HEX

LIGHT: Dict[str, str] = {
    "bg": "#F2F2F7",
    "sidebar": "#E9E9EE",
    "surface": "#FFFFFF",
    "hover": "#F0F0F5",
    "text": "#1C1C1E",
    "text_muted": "#6E6E73",
    "border": "#D8D8DD",
    "accent": "#0A84FF",
    "accent_text": "#FFFFFF",
    "selection": "#DCEBFF",
    "code_bg": "#EEEEF2",
}

DARK: Dict[str, str] = {
    "bg": "#1C1C1E",
    "sidebar": "#232325",
    "surface": "#2C2C2E",
    "hover": "#363638",
    "text": "#F2F2F7",
    "text_muted": "#98989E",
    "border": "#3A3A3C",
    "accent": "#0A84FF",
    "accent_text": "#FFFFFF",
    "selection": "#16365C",
    "code_bg": "#3A3A3C",
}


def resource_dir() -> Path:
    """Project root when run from source, bundle resources when frozen by PyInstaller."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


class Fonts:
    def __init__(self) -> None:
        self.display_family: Optional[str] = None
        for ttf in sorted((resource_dir() / "font").glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(ttf))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams and not self.display_family:
                self.display_family = fams[0]
        self.ui = QApplication.font()
        self.ui.setPointSize(13 if sys.platform == "darwin" else 10)

    def ui_font(self, delta: int = 0, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(self.ui)
        f.setPointSize(self.ui.pointSize() + delta)
        f.setWeight(weight)
        return f

    def display(self, size: int, weight: QFont.Weight = QFont.Weight.Light) -> QFont:
        """Poppins (from ./font) for titles; falls back to the system font."""
        if self.display_family:
            f = QFont(self.display_family)
            f.setPointSize(size)
            f.setWeight(weight)
            return f
        return self.ui_font(size - self.ui.pointSize(), QFont.Weight.DemiBold)

    def mono(self, delta: int = 0) -> QFont:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(self.ui.pointSize() + delta)
        return f


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def palette_for(mode: str) -> Dict[str, str]:
    dark = system_is_dark() if mode == "system" else mode == "dark"
    return DARK if dark else LIGHT


def apply(app: QApplication, p: Dict[str, str]) -> None:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p["bg"], QPalette.ColorRole.WindowText: p["text"],
        QPalette.ColorRole.Base: p["surface"], QPalette.ColorRole.AlternateBase: p["hover"],
        QPalette.ColorRole.Text: p["text"], QPalette.ColorRole.Button: p["surface"],
        QPalette.ColorRole.ButtonText: p["text"], QPalette.ColorRole.Highlight: p["accent"],
        QPalette.ColorRole.HighlightedText: p["accent_text"], QPalette.ColorRole.ToolTipBase: p["surface"],
        QPalette.ColorRole.ToolTipText: p["text"], QPalette.ColorRole.PlaceholderText: p["text_muted"],
        QPalette.ColorRole.Link: p["accent"], QPalette.ColorRole.Mid: p["border"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p["text_muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p["text_muted"]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(p))


def arrow_icon(color: str) -> str:
    """Small chevron PNG for combo-like controls (stylesheets can only reference files)."""
    path = Path(tempfile.gettempdir()) / f"micronotes-arrow-{color.lstrip('#')}.png"
    if not path.exists():
        pm = QPixmap(20, 12)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QPointF(3, 3), QPointF(10, 9), QPointF(17, 3)])
        painter.end()
        pm.save(str(path))
    return path.as_posix()


def stylesheet(p: Dict[str, str]) -> str:
    return f"""
    QMainWindow, QWidget#editorPanel, QWidget#listPanel {{ background: {p['bg']}; }}
    QWidget#sidebar {{ background: {p['sidebar']}; }}
    QSplitter::handle {{ background: {p['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}

    QLineEdit, QDateTimeEdit {{
        background: {p['surface']}; color: {p['text']};
        border: 1px solid {p['border']}; border-radius: 7px; padding: 5px 8px;
        selection-background-color: {p['accent']}; selection-color: {p['accent_text']};
    }}
    QLineEdit:focus, QDateTimeEdit:focus {{ border: 1px solid {p['accent']}; }}
    QLineEdit#titleEdit {{ background: transparent; border: none; padding: 2px 0; }}
    QDateTimeEdit:disabled {{ color: {p['text_muted']}; }}
    QDateTimeEdit::drop-down {{ border: none; width: 18px; }}
    QDateTimeEdit::down-arrow {{ image: url("{arrow_icon(p['text_muted'])}"); width: 10px; height: 6px; }}

    QPlainTextEdit, QTextBrowser {{
        background: {p['surface']}; color: {p['text']};
        border: 1px solid {p['border']}; border-radius: 10px; padding: 10px 12px;
        selection-background-color: {p['accent']}; selection-color: {p['accent_text']};
    }}
    QPlainTextEdit:focus {{ border: 1px solid {p['accent']}; }}

    QListView, QListWidget {{ background: transparent; border: none; outline: 0; }}
    QListWidget#sidebarList::item {{ padding: 5px 10px; border-radius: 6px; color: {p['text']}; }}
    QListWidget#sidebarList::item:hover {{ background: {p['hover']}; }}
    QListWidget#sidebarList::item:selected {{ background: {p['selection']}; color: {p['text']}; }}

    QPushButton, QToolButton {{
        background: {p['surface']}; color: {p['text']};
        border: 1px solid {p['border']}; border-radius: 7px; padding: 5px 12px;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {p['hover']}; }}
    QPushButton:checked, QToolButton:checked {{
        background: {p['selection']}; border-color: {p['accent']}; color: {p['text']};
    }}
    QPushButton#primary {{ background: {p['accent']}; color: {p['accent_text']}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: #3D9BFF; }}
    QPushButton#segLeft {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
    QPushButton#segRight {{ border-top-left-radius: 0; border-bottom-left-radius: 0; margin-left: -1px; }}

    QLabel {{ color: {p['text']}; background: transparent; }}
    QLabel#muted, QLabel#sectionTitle {{ color: {p['text_muted']}; }}
    QLabel#emptyState {{ color: {p['text_muted']}; font-size: 15px; }}
    QCheckBox {{ color: {p['text']}; spacing: 6px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['text_muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; }}
    QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    QMenu::item:selected {{ background: {p['accent']}; color: {p['accent_text']}; }}
    QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    """


def label_color(name: str) -> Optional[QColor]:
    hexv = COLOR_HEX.get(name)
    return QColor(hexv) if hexv else None
