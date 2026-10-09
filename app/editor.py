"""Markdown editor (with highlighting and list helpers) and the clickable preview."""
from __future__ import annotations

import re
from typing import Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QColor, QFont, QKeyEvent, QMouseEvent, QSyntaxHighlighter,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser

from .mdtools import FENCE_RE, LIST_RE, TASK_RE, continue_list
from .theme import Fonts

INLINE = {
    "code": re.compile(r"`[^`]+`"),
    "bold": re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"),
    "italic": re.compile(r"(?<![\w*_])([*_])(?![*_\s])(.+?)(?<![\s*_])\1(?![\w*_])"),
    "strike": re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"),
    "link": re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+"),
    "tag": re.compile(r"(?<![\w&])#[^\s#]+"),
}
HEADING_RE = re.compile(r"^(#{1,6})\s+.*")
QUOTE_RE = re.compile(r"^\s*>.*")


def select_block(c: QTextCursor) -> None:
    """Selects the whole paragraph (LineUnderCursor would select only the visual line)."""
    c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, doc: QTextDocument, fonts: Fonts):
        super().__init__(doc)
        self.fonts = fonts
        self.f: Dict[str, QTextCharFormat] = {}

    def set_palette(self, p: Dict[str, str]) -> None:
        def fmt(color=None, bold=False, italic=False, strike=False, mono=False, bg=None, size=0):
            f = QTextCharFormat()
            if color:
                f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            if strike:
                f.setFontStrikeOut(True)
            if mono:
                f.setFontFamilies([self.fonts.mono().family()])
            if bg:
                f.setBackground(QColor(bg))
            if size:
                f.setFontPointSize(self.fonts.ui.pointSize() + size)
            return f

        self.f = {
            "h1": fmt(p["text"], bold=True, size=5), "h2": fmt(p["text"], bold=True, size=3),
            "h3": fmt(p["text"], bold=True, size=1), "hmark": fmt(p["text_muted"]),
            "bold": fmt(bold=True), "italic": fmt(italic=True), "strike": fmt(p["text_muted"], strike=True),
            "code": fmt(mono=True, bg=p["code_bg"]), "link": fmt(p["accent"]), "tag": fmt(p["accent"]),
            "quote": fmt(p["text_muted"], italic=True), "marker": fmt(p["accent"], bold=True),
            "done": fmt(p["text_muted"], strike=True),
        }
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        if not self.f:
            return
        in_code = self.previousBlockState() == 1
        if FENCE_RE.match(text):
            self.setFormat(0, len(text), self.f["code"])
            self.setCurrentBlockState(0 if in_code else 1)
            return
        if in_code:
            self.setFormat(0, len(text), self.f["code"])
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)

        if m := HEADING_RE.match(text):
            level = len(m.group(1))
            self.setFormat(0, len(text), self.f["h1" if level == 1 else "h2" if level == 2 else "h3"])
            self.setFormat(0, level, self.f["hmark"])
            return
        if QUOTE_RE.match(text):
            self.setFormat(0, len(text), self.f["quote"])
        if m := TASK_RE.match(text):
            self.setFormat(0, m.end(), self.f["marker"])
            if m.group(2) in "xX":
                self.setFormat(m.end(), len(text) - m.end(), self.f["done"])
                return
        elif m := LIST_RE.match(text):
            self.setFormat(0, m.end(), self.f["marker"])
        for key in ("bold", "italic", "strike", "link", "tag", "code"):
            for mm in INLINE[key].finditer(text):
                self.setFormat(mm.start(), mm.end() - mm.start(), self.f[key])


class MarkdownEditor(QPlainTextEdit):
    def __init__(self, fonts: Fonts):
        super().__init__()
        self.setFont(fonts.ui_font(1))
        self.setTabChangesFocus(False)
        self.setPlaceholderText("Write in Markdown…  **bold**  *italic*  - [ ] task  # Heading")
        self.highlighter = MarkdownHighlighter(self.document(), fonts)

    # ——— key handling: list continuation and indentation
    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        key, mods = e.key(), e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        c = self.textCursor()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier \
                and not c.hasSelection() and c.atBlockEnd():
            prefix = continue_list(c.block().text())
            if prefix == "":
                # Enter on an empty list item ends the list
                select_block(c)
                c.removeSelectedText()
                return
            if prefix:
                c.insertText("\n" + prefix)
                self.ensureCursorVisible()
                return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and LIST_RE.match(c.block().text()):
            self._indent(outdent=key == Qt.Key.Key_Backtab or bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return
        super().keyPressEvent(e)

    def _indent(self, outdent: bool) -> None:
        c = self.textCursor()
        c.beginEditBlock()
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        if outdent:
            text = c.block().text()
            n = min(len(text) - len(text.lstrip(" ")), 2)
            c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, n)
            c.removeSelectedText()
        else:
            c.insertText("  ")
        c.endEditBlock()

    # ——— formatting commands
    def wrap(self, marker: str) -> None:
        c = self.textCursor()
        if c.hasSelection():
            text = c.selectedText()
            if text.startswith(marker) and text.endswith(marker) and len(text) >= 2 * len(marker):
                c.insertText(text[len(marker):-len(marker)])
            else:
                c.insertText(f"{marker}{text}{marker}")
        else:
            c.insertText(marker * 2)
            c.movePosition(QTextCursor.MoveOperation.Left, n=len(marker))
            self.setTextCursor(c)

    def toggle_checklist(self) -> None:
        c = self.textCursor()
        start, end = sorted((c.selectionStart(), c.selectionEnd()))
        doc = self.document()
        first, last = doc.findBlock(start), doc.findBlock(end)
        c.beginEditBlock()
        block = first
        while block.isValid():
            text = block.text()
            if m := TASK_RE.match(text):
                lm = LIST_RE.match(text)
                new = text[:lm.start(6)] + text[lm.end(6):] if lm and lm.group(6) else text
            elif m := LIST_RE.match(text):
                new = text[:m.end()] + "[ ] " + text[m.end():]
            else:
                indent = len(text) - len(text.lstrip())
                new = text[:indent] + "- [ ] " + text[indent:]
            bc = QTextCursor(block)
            select_block(bc)
            bc.insertText(new)
            if block == last:
                break
            block = block.next()
        c.endEditBlock()

    def insert_heading(self) -> None:
        c = self.textCursor()
        text = c.block().text()
        m = HEADING_RE.match(text)
        level = len(m.group(1)) if m else 0
        body = text[level:].lstrip() if m else text
        new = body if level >= 3 else "#" * (level + 1) + " " + body
        select_block(c)
        c.insertText(new)


class MarkdownPreview(QTextBrowser):
    """Rendered note. Clicking a checkbox emits taskToggled(index of the task in the note)."""
    taskToggled = Signal(int)

    def __init__(self, fonts: Fonts):
        super().__init__()
        self.setOpenExternalLinks(True)
        self.setFont(fonts.ui_font(1))
        self.setPlaceholderText("Nothing to preview")
        self.setMouseTracking(True)

    def set_markdown(self, source: str) -> None:
        bar = self.verticalScrollBar()
        pos = bar.value()
        self.document().setMarkdown(source, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        bar.setValue(pos)

    def _task_index_at(self, e: QMouseEvent):
        c = self.cursorForPosition(e.position().toPoint())
        block = c.block()
        if block.blockFormat().marker() == QTextBlockFormat.MarkerType.NoMarker:
            return None
        start = QTextCursor(block)
        if e.position().x() > self.cursorRect(start).left() + 2:
            return None
        idx = 0
        b = self.document().firstBlock()
        while b.isValid() and b != block:
            if b.blockFormat().marker() != QTextBlockFormat.MarkerType.NoMarker:
                idx += 1
            b = b.next()
        return idx

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        super().mouseMoveEvent(e)
        if self._task_index_at(e) is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and not self.textCursor().hasSelection():
            idx = self._task_index_at(e)
            if idx is not None:
                self.taskToggled.emit(idx)
                return
        super().mouseReleaseEvent(e)
