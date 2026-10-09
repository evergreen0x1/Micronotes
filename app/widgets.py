"""Custom painted widgets: note cards, sidebar rows, colour picker."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QToolButton, QWidget)

from .formats import COLOR_HEX
from .storage import COLORS, REMIND_FMT, TIME_FMT, parse_time
from .theme import Fonts

NOTE_ROLE = Qt.ItemDataRole.UserRole  # note id
PREVIEW_ROLE = Qt.ItemDataRole.UserRole + 1
TASKS_ROLE = Qt.ItemDataRole.UserRole + 2

FILTER_ROLE = Qt.ItemDataRole.UserRole
COUNT_ROLE = Qt.ItemDataRole.UserRole + 1
HEADER_ROLE = Qt.ItemDataRole.UserRole + 2


def short_date(value: str, fmt: str = TIME_FMT) -> str:
    dt = parse_time(value, fmt)
    if not dt:
        return ""
    today = datetime.now()
    if dt.date() == today.date():
        return dt.strftime("%H:%M")
    if dt.year == today.year:
        return f"{dt.day} {dt:%b}"
    return f"{dt.day} {dt:%b %Y}"


def remind_label(value: str) -> str:
    dt = parse_time(value, REMIND_FMT)
    if not dt:
        return ""
    if dt.date() == datetime.now().date():
        return dt.strftime("%H:%M")
    return f"{short_date(value, REMIND_FMT)} {dt:%H:%M}"


def color_dot(name: str, size: int = 12) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(COLOR_HEX[name]))
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.end()
    return QIcon(pm)


class NoteDelegate(QStyledItemDelegate):
    HEIGHT = 78

    def __init__(self, fonts: Fonts, parent=None):
        super().__init__(parent)
        self.fonts = fonts
        self.p: Dict[str, str] = {}
        self.by_id: Dict[str, dict] = {}  # id -> note, kept current by the window
        self.f_title = fonts.ui_font(1, QFont.Weight.DemiBold)
        self.f_body = fonts.ui_font(-1)
        self.f_small = fonts.ui_font(-2)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, self.HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        n = self.by_id.get(index.data(NOTE_ROLE))
        if not n or not self.p:
            return
        p = self.p
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect.adjusted(8, 3, -8, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        card = QPainterPath()
        card.addRoundedRect(QRectF(r), 9, 9)
        bg = p["selection"] if selected else p["surface"] if not hover else p["hover"]
        painter.fillPath(card, QColor(bg))
        if selected:
            painter.setPen(QColor(p["accent"]))
            painter.drawPath(card)
        if n["Color"] in COLOR_HEX:
            stripe = QPainterPath()
            stripe.addRoundedRect(QRectF(r.left() + 4, r.top() + 8, 4, r.height() - 16), 2, 2)
            painter.fillPath(stripe, QColor(COLOR_HEX[n["Color"]]))

        x, w = r.left() + 16, r.width() - 28
        top = r.top() + 8

        # line 1: title + date
        painter.setFont(self.f_small)
        date = short_date(n["Time"])
        fm_s = QFontMetrics(self.f_small)
        dw = fm_s.horizontalAdvance(date)
        painter.setPen(QColor(p["text_muted"]))
        painter.drawText(QRect(r.right() - 12 - dw, top + 2, dw, 18), Qt.AlignmentFlag.AlignRight, date)
        painter.setFont(self.f_title)
        painter.setPen(QColor(p["text"]))
        title = ("📌 " if n["Pinned"] else "") + (n["Subject"] or "Untitled")
        title = QFontMetrics(self.f_title).elidedText(title, Qt.TextElideMode.ElideRight, w - dw - 10)
        painter.drawText(QRect(x, top, w - dw - 10, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # line 2: preview
        painter.setFont(self.f_body)
        painter.setPen(QColor(p["text_muted"]))
        preview = index.data(PREVIEW_ROLE) or "No additional text"
        preview = QFontMetrics(self.f_body).elidedText(preview, Qt.TextElideMode.ElideRight, w)
        painter.drawText(QRect(x, top + 22, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, preview)

        # line 3: tags, reminder, tasks
        painter.setFont(self.f_small)
        right = []
        done, total = index.data(TASKS_ROLE) or (0, 0)
        if total:
            right.append(f"☑ {done}/{total}")
        if n["Remind"]:
            right.append(("✓ " if n["Reminded"] else "🔔 ") + remind_label(n["Remind"]))
        rtext = "   ".join(right)
        rw = fm_s.horizontalAdvance(rtext)
        if rtext:
            painter.setPen(QColor(p["accent"] if n["Remind"] and not n["Reminded"] else p["text_muted"]))
            painter.drawText(QRect(r.right() - 12 - rw, top + 42, rw, 18), Qt.AlignmentFlag.AlignRight, rtext)
        if n["Tags"]:
            painter.setPen(QColor(p["accent"]))
            tags = fm_s.elidedText("  ".join("#" + t for t in n["Tags"]), Qt.TextElideMode.ElideRight, w - rw - 10)
            painter.drawText(QRect(x, top + 42, w - rw - 10, 18), Qt.AlignmentFlag.AlignLeft, tags)
        painter.restore()


class SidebarDelegate(QStyledItemDelegate):
    """Section headers in small caps, counters right-aligned."""

    def __init__(self, fonts: Fonts, parent=None):
        super().__init__(parent)
        self.p: Dict[str, str] = {}
        self.f_head = fonts.ui_font(-3, QFont.Weight.DemiBold)
        self.f_head.setCapitalization(QFont.Capitalization.AllUppercase)
        self.f_head.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        self.f_row = fonts.ui_font(0)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(150, 34 if index.data(HEADER_ROLE) else 28)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if not self.p:
            return
        p = self.p
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        if index.data(HEADER_ROLE):
            painter.setFont(self.f_head)
            painter.setPen(QColor(p["text_muted"]))
            painter.drawText(r.adjusted(14, 10, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             index.data(Qt.ItemDataRole.DisplayRole))
            painter.restore()
            return
        rr = r.adjusted(6, 1, -6, -1)
        if option.state & QStyle.StateFlag.State_Selected:
            path = QPainterPath()
            path.addRoundedRect(QRectF(rr), 6, 6)
            painter.fillPath(path, QColor(p["selection"]))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            path = QPainterPath()
            path.addRoundedRect(QRectF(rr), 6, 6)
            painter.fillPath(path, QColor(p["hover"]))
        x = rr.left() + 8
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(painter, QRect(x, rr.center().y() - 6, 12, 12))
            x += 20
        painter.setFont(self.f_row)
        count = index.data(COUNT_ROLE)
        ctext = str(count) if count else ""
        cw = QFontMetrics(self.f_row).horizontalAdvance(ctext)
        painter.setPen(QColor(p["text_muted"]))
        painter.drawText(QRect(rr.right() - 8 - cw, rr.top(), cw, rr.height()), Qt.AlignmentFlag.AlignVCenter, ctext)
        painter.setPen(QColor(p["text"]))
        text = QFontMetrics(self.f_row).elidedText(index.data(Qt.ItemDataRole.DisplayRole),
                                                    Qt.TextElideMode.ElideRight, rr.right() - 14 - cw - x)
        painter.drawText(QRect(x, rr.top(), rr.right() - x, rr.height()), Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class ColorPicker(QWidget):
    colorChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: Dict[str, QToolButton] = {}
        for name in COLORS:
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(20, 20)
            b.setToolTip(name.capitalize() if name else "No colour")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if not name:
                b.setText("✕")
            self.group.addButton(b)
            self.buttons[name] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, n=name: self.colorChanged.emit(n))
        self.p: Optional[Dict[str, str]] = None

    def set_palette(self, p: Dict[str, str]) -> None:
        self.p = p
        for name, b in self.buttons.items():
            bg = COLOR_HEX.get(name, p["surface"])
            b.setStyleSheet(
                f"QToolButton {{ background: {bg}; border: 1px solid {p['border']}; border-radius: 10px;"
                f" padding: 0; color: {p['text_muted']}; font-size: 10px; }}"
                f"QToolButton:checked {{ border: 2px solid {p['text']}; }}")

    def set_color(self, name: str) -> None:
        b = self.buttons.get(name) or self.buttons[""]
        b.setChecked(True)
