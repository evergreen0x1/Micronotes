"""Main window: sidebar (filters) | notes list | editor."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import (QByteArray, QDateTime, QFileSystemWatcher, QItemSelectionModel,
                            QStringListModel, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeyEvent, QKeySequence,
                           QShortcut, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCompleter,
                               QDateTimeEdit, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from . import formats, theme
from .editor import MarkdownEditor, MarkdownPreview
from .mdtools import plain_preview, task_counts, toggle_task
from .notify import notify
from .storage import (COLORS, MAX_DESC, MAX_NOTES, MAX_SUBJECT, REMIND_FMT, LoadError, Note,
                      Settings, Store, default_data_dir, due_reminders, icloud_data_dir, is_empty,
                      merge, new_note, next_full_hour, normalize_all, now, parse_tags, parse_time,
                      read_notes_file)
from .widgets import (COUNT_ROLE, FILTER_ROLE, HEADER_ROLE, NOTE_ROLE, PREVIEW_ROLE, TASKS_ROLE,
                      ColorPicker, NoteDelegate, SidebarDelegate, color_dot)

Filter = Tuple[str, ...]
SAVE_DELAY_MS = 600
REMINDER_CHECK_MS = 20_000
UNDO_DEPTH = 20


def md_to_html(source: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(source, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    html = doc.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    return m.group(1) if m else html


def full_date(value: str) -> str:
    dt = parse_time(value)
    return f"{dt.day} {dt:%b %Y, %H:%M}" if dt else ""


class TagEdit(QLineEdit):
    """Comma separated tags with completion of the tag being typed."""

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("Tags, comma separated")
        self.model = QStringListModel()
        self.comp = QCompleter(self.model, self)
        self.comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.comp.setWidget(self)
        self.comp.activated.connect(self._insert)
        self.textEdited.connect(self._update)

    def set_tags(self, tags: List[str]) -> None:
        self.model.setStringList(tags)

    def _token(self) -> str:
        return self.text()[: self.cursorPosition()].split(",")[-1].strip().lstrip("#")

    def _update(self) -> None:
        token = self._token()
        if not token:
            self.comp.popup().hide()
            return
        self.comp.setCompletionPrefix(token)
        if self.comp.completionCount() and self.comp.currentCompletion().lower() != token.lower():
            self.comp.complete()
        else:
            self.comp.popup().hide()

    def _insert(self, tag: str) -> None:
        pos = self.cursorPosition()
        head, tail = self.text()[:pos], self.text()[pos:]
        parts = head.split(",")
        parts[-1] = (" " if len(parts) > 1 else "") + tag
        new_head = ",".join(parts) + ", "
        self.setText(new_head + tail.lstrip(", "))
        self.setCursorPosition(len(new_head))
        self.textEdited.emit(self.text())


class NotesList(QListWidget):
    """Notes list with its own keys: Delete/⌫/⌘⌫ delete, ⌘Z undoes a delete, ⌘C copies, Return edits."""
    deleteRequested = Signal()
    undoRequested = Signal()
    copyRequested = Signal()
    openRequested = Signal()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleteRequested.emit()
        elif e.matches(QKeySequence.StandardKey.Undo):
            self.undoRequested.emit()
        elif e.matches(QKeySequence.StandardKey.Copy):
            self.copyRequested.emit()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.openRequested.emit()
        else:
            super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None):
        super().__init__()
        self.setWindowTitle("Micronotes")
        self.setMinimumSize(900, 560)
        self.settings = settings or Settings()
        self.fonts = theme.Fonts()
        self.store = Store(self.settings.data_dir())
        warning = self.store.load()

        self.current_id: Optional[str] = None
        self.dirty = False
        self.loading = False        # filling the editor programmatically
        self.loading_list = False   # rebuilding the list programmatically
        self.undo_stack: List[List[Note]] = []
        self.filter: Filter = ("all",)
        self.sort_key = self.settings.get("sort", "updated")
        self.theme_mode = self.settings.get("theme", "system")
        self.by_id: Dict[str, Note] = {}
        self.preview_cache: Dict[str, Tuple[str, str, Tuple[int, int]]] = {}

        self.save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS, timeout=self.commit_editor)
        self.reload_timer = QTimer(self, singleShot=True, interval=400, timeout=self.on_external_change)
        self.reminder_timer = QTimer(self, interval=REMINDER_CHECK_MS, timeout=self.check_reminders)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.reload_timer.start())
        self.watcher.fileChanged.connect(lambda _: self.reload_timer.start())

        self._build_ui()
        self._build_menus()
        self.apply_theme()
        self._restore_state()
        self._watch()

        self.refresh_sidebar()
        self.refresh_list(select_first=True)
        self.reminder_timer.start()
        QTimer.singleShot(1500, self.check_reminders)
        QApplication.styleHints().colorSchemeChanged.connect(
            lambda _: self.theme_mode == "system" and self.apply_theme())
        QApplication.instance().aboutToQuit.connect(self.persist)
        if warning:
            QTimer.singleShot(300, lambda: QMessageBox.warning(self, "Micronotes", warning))

    # ——— UI construction
    def _build_ui(self) -> None:
        # sidebar
        self.sidebar = QWidget(objectName="sidebar")
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(4, 12, 4, 10)
        self.side_list = QListWidget(objectName="sidebarList")
        self.side_delegate = SidebarDelegate(self.fonts, self.side_list)
        self.side_list.setItemDelegate(self.side_delegate)
        self.side_list.setMouseTracking(True)
        self.side_list.currentItemChanged.connect(self.on_filter_changed)
        self.location_label = QLabel(objectName="muted")
        self.location_label.setFont(self.fonts.ui_font(-3))
        self.location_label.setWordWrap(True)
        self.location_label.setContentsMargins(12, 0, 8, 0)
        sl.addWidget(self.side_list, 1)
        sl.addWidget(self.location_label)

        # notes list
        list_panel = QWidget(objectName="listPanel")
        ll = QVBoxLayout(list_panel)
        ll.setContentsMargins(6, 12, 6, 8)
        ll.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(8, 0, 8, 0)
        self.search = QLineEdit(placeholderText="Search  (#tag to filter)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.refresh_list(select_first=True))
        self.search.returnPressed.connect(self.notes_focus)
        QShortcut(QKeySequence("Escape"), self.search, activated=self.search.clear,
                  context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence("Down"), self.search, activated=self.notes_focus,
                  context=Qt.ShortcutContext.WidgetShortcut)
        self.btn_new = QPushButton("＋ New", objectName="primary")
        self.btn_new.setToolTip("New note (⌘N)")
        self.btn_new.clicked.connect(self.new_note)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_new)
        self.notes = NotesList()
        self.note_delegate = NoteDelegate(self.fonts, self.notes)
        self.note_delegate.by_id = self.by_id
        self.notes.setItemDelegate(self.note_delegate)
        self.notes.setUniformItemSizes(True)
        self.notes.setMouseTracking(True)
        self.notes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.notes.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.notes.currentItemChanged.connect(self.on_current_changed)
        self.notes.itemSelectionChanged.connect(self.update_count)
        self.notes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes.customContextMenuRequested.connect(self.notes_menu)
        self.notes.deleteRequested.connect(self.delete_selected)
        self.notes.undoRequested.connect(self.undo_delete)
        self.notes.copyRequested.connect(self.copy_notes)
        self.notes.openRequested.connect(lambda: self.editor.setFocus())
        self.count_label = QLabel(objectName="muted")
        self.count_label.setFont(self.fonts.ui_font(-2))
        self.count_label.setContentsMargins(10, 0, 0, 0)
        ll.addLayout(top)
        ll.addWidget(self.notes, 1)
        ll.addWidget(self.count_label)

        # editor
        editor_panel = QWidget(objectName="editorPanel")
        el = QVBoxLayout(editor_panel)
        el.setContentsMargins(20, 14, 20, 10)
        self.editor_stack = QStackedWidget()
        el.addWidget(self.editor_stack)

        empty = QWidget()
        ell = QVBoxLayout(empty)
        ell.addStretch()
        lbl = QLabel("No note selected\n\nPress ⌘N to start writing", objectName="emptyState")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ell.addWidget(lbl)
        ell.addStretch()
        self.editor_stack.addWidget(empty)

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.title = QLineEdit(objectName="titleEdit", placeholderText="Title")
        self.title.setFont(self.fonts.display(24))
        self.title.setMaxLength(MAX_SUBJECT)
        self.title.textEdited.connect(self.on_edited)
        self.title.returnPressed.connect(lambda: self.editor.setFocus())

        row1 = QHBoxLayout()
        self.tags = TagEdit()
        self.tags.textEdited.connect(self.on_edited)
        self.tags.editingFinished.connect(self.normalize_tags_field)
        self.color = ColorPicker()
        self.color.colorChanged.connect(self.on_color)
        row1.addWidget(self.tags, 1)
        row1.addSpacing(8)
        row1.addWidget(self.color)

        row2 = QHBoxLayout()
        self.btn_pin = QToolButton(text="📌 Pin", checkable=True)
        self.btn_pin.setToolTip("Keep at the top of the list (⇧⌘P)")
        self.btn_pin.toggled.connect(self.on_pin)
        self.btn_remind = QToolButton(text="🔔 Remind", checkable=True)
        self.btn_remind.setToolTip("Get a macOS notification at the chosen time (⇧⌘R)")
        self.btn_remind.toggled.connect(self.on_remind_toggled)
        self.remind_at = QDateTimeEdit(calendarPopup=True)
        self.remind_at.setDisplayFormat("d MMM yyyy   HH:mm")
        self.remind_at.dateTimeChanged.connect(self.on_remind_changed)
        self.btn_edit = QPushButton("Edit", objectName="segLeft", checkable=True)
        self.btn_preview = QPushButton("Preview", objectName="segRight", checkable=True)
        mode = QButtonGroup(self)
        mode.addButton(self.btn_edit)
        mode.addButton(self.btn_preview)
        self.btn_edit.clicked.connect(lambda: self.set_preview(False))
        self.btn_preview.clicked.connect(lambda: self.set_preview(True))
        for w in (self.btn_pin, self.btn_remind, self.remind_at):
            row2.addWidget(w)
        row2.addStretch()
        row2.addWidget(self.btn_edit)
        row2.addWidget(self.btn_preview)

        self.body = QStackedWidget()
        self.editor = MarkdownEditor(self.fonts)
        self.editor.textChanged.connect(self.on_edited)
        self.preview = MarkdownPreview(self.fonts)
        self.preview.taskToggled.connect(self.on_task_toggled)
        self.body.addWidget(self.editor)
        self.body.addWidget(self.preview)

        self.footer = QLabel(objectName="muted")
        self.footer.setFont(self.fonts.ui_font(-2))

        pl.addWidget(self.title)
        pl.addLayout(row1)
        pl.addLayout(row2)
        pl.addWidget(self.body, 1)
        pl.addWidget(self.footer)
        self.editor_stack.addWidget(page)
        self.setTabOrder(self.title, self.tags)
        self.setTabOrder(self.tags, self.editor)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(list_panel)
        self.splitter.addWidget(editor_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([190, 330, 620])
        self.setCentralWidget(self.splitter)
        self.statusBar().setSizeGripEnabled(False)

    def _build_menus(self) -> None:
        mb = self.menuBar()

        def act(menu, text, slot, shortcut=None, checkable=False):
            a = QAction(text, self, checkable=checkable)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = mb.addMenu("File")
        act(m, "New Note", self.new_note, "Ctrl+N")
        act(m, "Duplicate Note", self.duplicate_note, "Ctrl+D")
        m.addSeparator()
        act(m, "Import…", self.import_notes, "Ctrl+Shift+I")
        act(m, "Export All…", lambda: self.export_notes(False), "Ctrl+Shift+E")
        act(m, "Export Selected…", lambda: self.export_notes(True))
        m.addSeparator()
        loc = m.addMenu("Data Location")
        self.loc_group = QActionGroup(self)
        self.act_loc_local = act(loc, "This Mac (default)", lambda: self.switch_data_dir(default_data_dir()), checkable=True)
        self.act_loc_icloud = act(loc, "iCloud Drive", self.use_icloud, checkable=True)
        self.act_loc_custom = act(loc, "Custom Folder…", self.choose_data_dir, checkable=True)
        for a in (self.act_loc_local, self.act_loc_icloud, self.act_loc_custom):
            self.loc_group.addAction(a)
        self.act_loc_icloud.setEnabled(icloud_data_dir() is not None)
        loc.addSeparator()
        act(loc, "Show in Finder", self.show_data_folder)

        m = mb.addMenu("Edit")
        act(m, "Find", self.focus_search, "Ctrl+F")
        m.addSeparator()
        act(m, "Bold", lambda: self.format_cmd("bold"), "Ctrl+B")
        act(m, "Italic", lambda: self.format_cmd("italic"), "Ctrl+I")
        act(m, "Strikethrough", lambda: self.format_cmd("strike"), "Ctrl+Shift+X")
        act(m, "Checklist", lambda: self.format_cmd("check"), "Ctrl+Shift+L")
        act(m, "Heading", lambda: self.format_cmd("heading"), "Ctrl+Shift+H")

        m = mb.addMenu("Note")
        act(m, "Pin / Unpin", self.toggle_pin_selected, "Ctrl+Shift+P")
        act(m, "Set Reminder", lambda: self.current_id and self.btn_remind.toggle(), "Ctrl+Shift+R")
        act(m, "Toggle Preview", lambda: self.set_preview(not self.btn_preview.isChecked()), "Ctrl+E")
        act(m, "Copy as Markdown", self.copy_notes)
        m.addSeparator()
        act(m, "Delete", self.delete_selected)
        self.act_undo_delete = act(m, "Undo Delete", self.undo_delete)

        m = mb.addMenu("View")
        self.act_sidebar = act(m, "Show Sidebar", self.toggle_sidebar, "Ctrl+Alt+S", checkable=True)
        sort = m.addMenu("Sort By")
        g = QActionGroup(self)
        for key, text in (("updated", "Date Updated"), ("created", "Date Created"), ("title", "Title")):
            a = act(sort, text, lambda _=False, k=key: self.set_sort(k), checkable=True)
            a.setChecked(key == self.sort_key)
            g.addAction(a)
        th = m.addMenu("Theme")
        g = QActionGroup(self)
        for key, text in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
            a = act(th, text, lambda _=False, k=key: self.set_theme(k), checkable=True)
            a.setChecked(key == self.theme_mode)
            g.addAction(a)

    def _restore_state(self) -> None:
        for key, fn in (("geometry", self.restoreGeometry), ("splitter", self.splitter.restoreState)):
            v = self.settings.get(key)
            if isinstance(v, str):
                fn(QByteArray.fromBase64(v.encode()))
        self.sidebar.setVisible(self.settings.get("sidebar", True))
        self.act_sidebar.setChecked(self.sidebar.isVisible())
        self.set_preview(bool(self.settings.get("preview", False)))

    # ——— theme
    def apply_theme(self) -> None:
        self.p = theme.palette_for(self.theme_mode)
        theme.apply(QApplication.instance(), self.p)
        self.note_delegate.p = self.p
        self.side_delegate.p = self.p
        self.color.set_palette(self.p)
        self.editor.highlighter.set_palette(self.p)
        self.statusBar().setStyleSheet(f"QStatusBar {{ background: {self.p['bg']}; color: {self.p['text_muted']}; }}")
        self.notes.viewport().update()
        self.side_list.viewport().update()

    def set_theme(self, mode: str) -> None:
        self.theme_mode = self.settings["theme"] = mode
        self.settings.save()
        self.apply_theme()

    # ——— persistence
    def save(self) -> bool:
        if self.store.mtime() != self.store.last_mtime:
            self.on_external_change()
        try:
            self.store.save()
            return True
        except OSError as e:
            QMessageBox.critical(self, "Micronotes", f"Could not save notes:\n{e}")
            return False

    def persist(self) -> None:
        self.commit_editor()
        self.drop_if_empty(self.current_id)
        self.settings.update({
            "geometry": self.saveGeometry().toBase64().data().decode(),
            "splitter": self.splitter.saveState().toBase64().data().decode(),
            "sidebar": self.sidebar.isVisible(),
            "preview": self.btn_preview.isChecked(),
            "sort": self.sort_key,
        })
        self.settings.save()

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        self.persist()
        super().closeEvent(e)

    def _watch(self) -> None:
        for paths in (self.watcher.files(), self.watcher.directories()):
            if paths:
                self.watcher.removePaths(paths)
        self.store.data_dir.mkdir(parents=True, exist_ok=True)
        self.watcher.addPath(str(self.store.data_dir))
        if self.store.path.exists():
            self.watcher.addPath(str(self.store.path))
        d = self.store.data_dir
        icloud = icloud_data_dir()
        self.act_loc_local.setChecked(d == default_data_dir())
        self.act_loc_icloud.setChecked(icloud is not None and d == icloud)
        self.act_loc_custom.setChecked(not (self.act_loc_local.isChecked() or self.act_loc_icloud.isChecked()))
        where = "This Mac" if self.act_loc_local.isChecked() else "iCloud Drive" if self.act_loc_icloud.isChecked() else str(d)
        self.location_label.setText(f"Stored in: {where}")
        self.location_label.setToolTip(str(self.store.path))

    def on_external_change(self) -> None:
        """notes.json changed outside the app (another Mac via iCloud, a sync tool, a text editor)."""
        if str(self.store.path) not in self.watcher.files() and self.store.path.exists():
            self.watcher.addPath(str(self.store.path))
        mt = self.store.mtime()
        if mt is None or mt == self.store.last_mtime:
            return
        try:
            disk = read_notes_file(self.store.path)
        except (LoadError, OSError):
            return  # probably mid-write; the next change event retries
        pending = None
        if self.dirty and self.current_id:
            self.apply_editor_to_note()
            pending = self.store.get(self.current_id)
        local_new = [n for n in self.store.notes if is_empty(n) and n["id"] == self.current_id]
        self.store.notes = disk
        self.store.last_mtime = mt
        if pending:
            self.store.notes = merge(self.store.notes, [pending])
        for n in local_new:
            if not self.store.get(n["id"]):
                self.store.notes.append(n)
        if pending:
            self.dirty = False
            try:
                self.store.save()
            except OSError:
                pass
        self.refresh_sidebar()
        self.refresh_list()
        if not self.dirty:
            self.show_note(self.current_id if self.store.get(self.current_id) else None, keep_cursor=True)
        self.flash("Notes updated from disk")

    # ——— sidebar / list
    def refresh_sidebar(self) -> None:
        notes = self.store.notes
        self.side_list.blockSignals(True)
        self.side_list.clear()

        def header(text: str) -> None:
            it = QListWidgetItem(text)
            it.setData(HEADER_ROLE, True)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.side_list.addItem(it)

        def row(text: str, flt: Filter, count: int, icon=None) -> None:
            it = QListWidgetItem(text)
            it.setData(FILTER_ROLE, list(flt))
            it.setData(COUNT_ROLE, count)
            if icon:
                it.setIcon(icon)
            self.side_list.addItem(it)

        header("Library")
        row("🗂  All Notes", ("all",), len(notes))
        row("📌  Pinned", ("pinned",), sum(n["Pinned"] for n in notes))
        row("🔔  Reminders", ("reminders",), sum(bool(n["Remind"]) and not n["Reminded"] for n in notes))
        tags = self.store.all_tags()
        if tags:
            header("Tags")
            for t, c in tags.items():
                row(f"# {t}", ("tag", t.lower()), c)
        used = [c for c in COLORS if c and any(n["Color"] == c for n in notes)]
        if used:
            header("Colors")
            for c in used:
                row(c.capitalize(), ("color", c), sum(n["Color"] == c for n in notes), color_dot(c))
        self.tags.set_tags(list(tags))

        target = 1
        for i in range(self.side_list.count()):
            if tuple(self.side_list.item(i).data(FILTER_ROLE) or ()) == self.filter:
                target = i
        self.side_list.setCurrentRow(target)
        self.filter = tuple(self.side_list.item(target).data(FILTER_ROLE))
        self.side_list.blockSignals(False)

    def on_filter_changed(self, item: Optional[QListWidgetItem], _prev=None) -> None:
        if item is None or not item.data(FILTER_ROLE):
            return
        self.filter = tuple(item.data(FILTER_ROLE))
        self.refresh_list(select_first=True)

    def visible_notes(self) -> List[Note]:
        kind = self.filter[0]
        items = self.store.notes
        if kind == "pinned":
            items = [n for n in items if n["Pinned"]]
        elif kind == "reminders":
            items = [n for n in items if n["Remind"] and not n["Reminded"]]
        elif kind == "tag":
            items = [n for n in items if self.filter[1] in (t.lower() for t in n["Tags"])]
        elif kind == "color":
            items = [n for n in items if n["Color"] == self.filter[1]]
        q = self.search.text().strip().lower()
        if q:
            tag_terms = [t[1:] for t in q.split() if t.startswith("#") and len(t) > 1]
            words = [t for t in q.split() if not t.startswith("#")]

            def match(n: Note) -> bool:
                tags = [t.lower() for t in n["Tags"]]
                if any(not any(t.startswith(tt) for t in tags) for tt in tag_terms):
                    return False
                hay = f"{n['Subject']}\n{n['Description']}\n{' '.join(tags)}".lower()
                return all(w in hay for w in words)
            items = [n for n in items if match(n)]
        if kind == "reminders":
            return sorted(items, key=lambda n: n["Remind"])
        if self.sort_key == "title":
            items = sorted(items, key=lambda n: (n["Subject"] or "￿").lower())
        else:
            key = "Created" if self.sort_key == "created" else "Time"
            items = sorted(items, key=lambda n: n[key], reverse=True)
        return sorted(items, key=lambda n: not n["Pinned"])

    def _preview_for(self, n: Note) -> Tuple[str, Tuple[int, int]]:
        cached = self.preview_cache.get(n["id"])
        key = n["Time"] + str(len(n["Description"]))
        if not cached or cached[0] != key:
            cached = (key, plain_preview(n["Description"]), task_counts(n["Description"]))
            self.preview_cache[n["id"]] = cached
        return cached[1], cached[2]

    def refresh_list(self, select_first: bool = False) -> None:
        """Rebuilds the list. With select_first the editor follows the list (filter/search changed);
        otherwise the note being edited stays open even if it no longer matches."""
        if select_first:
            self.commit_editor()
        self.loading_list = True
        selected = {it.data(NOTE_ROLE) for it in self.notes.selectedItems()}
        scroll = self.notes.verticalScrollBar().value()
        self.notes.clear()
        self.by_id.clear()
        current_row = None
        for i, n in enumerate(self.visible_notes()):
            self.by_id[n["id"]] = n
            preview, tasks = self._preview_for(n)
            it = QListWidgetItem()
            it.setData(NOTE_ROLE, n["id"])
            it.setData(PREVIEW_ROLE, preview)
            it.setData(TASKS_ROLE, tasks)
            self.notes.addItem(it)
            if n["id"] == self.current_id:
                current_row = i
        if current_row is not None:
            self.notes.setCurrentRow(current_row, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            if len(selected) > 1 and self.current_id in selected:  # keep a multi-selection
                for i in range(self.notes.count()):
                    if self.notes.item(i).data(NOTE_ROLE) in selected:
                        self.notes.item(i).setSelected(True)
            self.notes.verticalScrollBar().setValue(scroll)
        self.loading_list = False
        if current_row is None and select_first:
            prev = self.current_id
            self.show_note(self.notes.item(0).data(NOTE_ROLE) if self.notes.count() else None)
            self.drop_if_empty(prev)
            if self.notes.count():
                self.loading_list = True
                self.notes.setCurrentRow(0)
                self.loading_list = False
        self.update_count()

    def update_count(self) -> None:
        shown, total = self.notes.count(), len(self.store.notes)
        text = f"{total} notes" if shown == total else f"{shown} of {total} notes"
        sel = len(self.notes.selectedItems())
        if sel > 1:
            text += f"  ·  {sel} selected"
        self.count_label.setText(text)

    def on_current_changed(self, cur: Optional[QListWidgetItem], prev: Optional[QListWidgetItem]) -> None:
        if self.loading_list:
            return
        nid = cur.data(NOTE_ROLE) if cur else None
        if nid == self.current_id:
            return
        self.commit_editor()
        old = self.current_id
        self.show_note(nid)
        if self.drop_if_empty(old):
            self.refresh_list()

    def drop_if_empty(self, nid: Optional[str]) -> bool:
        """A new note left without any content is discarded."""
        n = self.store.get(nid)
        if n and is_empty(n) and nid != self.current_id:
            self.store.notes.remove(n)
            if self.store.path.exists():
                self.save()
            return True
        return False

    def notes_focus(self) -> None:
        if self.notes.count():
            self.notes.setFocus()
            if not self.notes.currentItem():
                self.notes.setCurrentRow(0)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def selected_ids(self) -> List[str]:
        ids = [it.data(NOTE_ROLE) for it in self.notes.selectedItems()]
        if not ids and self.current_id:
            ids = [self.current_id]
        return ids

    def select_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        rows = [i for i in range(self.notes.count()) if self.notes.item(i).data(NOTE_ROLE) in ids]
        if rows:
            self.notes.clearSelection()
            self.notes.setCurrentRow(rows[0])
            for r in rows:
                self.notes.item(r).setSelected(True)
            self.notes.scrollToItem(self.notes.item(rows[0]))

    def flash(self, message: str) -> None:
        self.statusBar().showMessage(message, 4000)

    # ——— editor
    def show_note(self, nid: Optional[str], keep_cursor: bool = False) -> None:
        n = self.store.get(nid)
        self.current_id = n["id"] if n else None
        self.dirty = False
        if not n:
            self.editor_stack.setCurrentIndex(0)
            return
        self.loading = True
        pos = self.editor.textCursor().position()
        self.title.setText(n["Subject"])
        self.tags.setText(", ".join(n["Tags"]))
        self.color.set_color(n["Color"])
        self.btn_pin.setChecked(n["Pinned"])
        self.editor.setPlainText(n["Description"])
        if keep_cursor:
            c = self.editor.textCursor()
            c.setPosition(min(pos, len(n["Description"])))
            self.editor.setTextCursor(c)
        self._show_reminder(n)
        if self.btn_preview.isChecked():
            self.preview.set_markdown(n["Description"])
        self.update_footer(n)
        self.editor_stack.setCurrentIndex(1)
        self.loading = False

    def _show_reminder(self, n: Note) -> None:
        dt = parse_time(n["Remind"], REMIND_FMT) if n["Remind"] else None
        self.btn_remind.setChecked(bool(dt))
        self.remind_at.setEnabled(bool(dt))
        self.remind_at.setDateTime(QDateTime(dt or next_full_hour()))
        self.btn_remind.setText("✓ Reminded" if n["Reminded"] else "🔔 Remind")

    def update_footer(self, n: Note) -> None:
        words = len(n["Description"].split())
        parts = [f"Created {full_date(n['Created'])}", f"Updated {full_date(n['Time'])}",
                 f"{words} word{'s' if words != 1 else ''}"]
        done, total = task_counts(n["Description"])
        if total:
            parts.append(f"{done}/{total} tasks done")
        if len(n["Description"]) > MAX_DESC * 0.9:
            parts.append(f"{len(n['Description'])}/{MAX_DESC} characters")
        self.footer.setText("   ·   ".join(parts))

    def on_edited(self, *_args) -> None:
        if self.loading or not self.current_id:
            return
        self.dirty = True
        self.save_timer.start()

    def apply_editor_to_note(self) -> Optional[Note]:
        n = self.store.get(self.current_id)
        if not n:
            return None
        desc = self.editor.toPlainText()
        if len(desc) > MAX_DESC:
            desc = desc[:MAX_DESC]
            self.flash(f"Notes are limited to {MAX_DESC} characters; the rest was not saved")
        n.update({"Subject": self.title.text().strip()[:MAX_SUBJECT],
                  "Tags": parse_tags(self.tags.text()), "Description": desc, "Time": now()})
        return n

    def commit_editor(self) -> None:
        self.save_timer.stop()
        if not self.dirty or not self.current_id:
            return
        n = self.apply_editor_to_note()
        self.dirty = False
        if not n:
            return
        tags_before = set(self.store.all_tags())
        self.save()
        self.update_footer(n)
        if set(self.store.all_tags()) != tags_before:
            self.refresh_sidebar()
        self.refresh_list()

    def normalize_tags_field(self) -> None:
        if self.loading or not self.current_id:
            return
        self.commit_editor()
        n = self.store.get(self.current_id)
        if n and not self.tags.hasFocus():
            self.tags.setText(", ".join(n["Tags"]))

    def _set_field(self, **fields) -> None:
        """Immediate (non-debounced) change of a note attribute."""
        if self.loading or not self.current_id:
            return
        self.commit_editor()
        n = self.store.get(self.current_id)
        if not n:
            return
        n.update(fields, Time=now())
        self.save()
        self.refresh_sidebar()
        self.refresh_list()
        self.update_footer(n)

    def on_color(self, name: str) -> None:
        self._set_field(Color=name)

    def on_pin(self, checked: bool) -> None:
        self._set_field(Pinned=checked)

    def on_remind_toggled(self, checked: bool) -> None:
        self.remind_at.setEnabled(checked)
        if self.loading or not self.current_id:
            return
        if checked:
            dt = self.remind_at.dateTime().toPython()
            if dt <= datetime.now():
                dt = next_full_hour()
                self.loading = True
                self.remind_at.setDateTime(QDateTime(dt))
                self.loading = False
            self._set_field(Remind=dt.strftime(REMIND_FMT), Reminded=False)
            self.flash(f"Reminder set for {dt:%d %b %Y %H:%M} — Micronotes must be running to notify you")
        else:
            self._set_field(Remind="", Reminded=False)
        self.btn_remind.setText("🔔 Remind")

    def on_remind_changed(self, qdt: QDateTime) -> None:
        if self.loading or not self.current_id or not self.btn_remind.isChecked():
            return
        self._set_field(Remind=qdt.toPython().strftime(REMIND_FMT), Reminded=False)
        self.btn_remind.setText("🔔 Remind")

    def set_preview(self, on: bool) -> None:
        self.btn_preview.setChecked(on)
        self.btn_edit.setChecked(not on)
        if on:
            self.preview.set_markdown(self.editor.toPlainText())
        self.body.setCurrentIndex(1 if on else 0)
        (self.preview if on else self.editor).setFocus()

    def on_task_toggled(self, index: int) -> None:
        new = toggle_task(self.editor.toPlainText(), index)
        c = self.editor.textCursor()
        c.select(c.SelectionType.Document)
        c.insertText(new)   # keeps the change in the editor's undo history
        self.preview.set_markdown(new)
        self.commit_editor()

    def format_cmd(self, cmd: str) -> None:
        if self.editor_stack.currentIndex() != 1:
            return
        if self.btn_preview.isChecked():
            self.set_preview(False)
        self.editor.setFocus()
        if cmd == "bold":
            self.editor.wrap("**")
        elif cmd == "italic":
            self.editor.wrap("*")
        elif cmd == "strike":
            self.editor.wrap("~~")
        elif cmd == "check":
            self.editor.toggle_checklist()
        elif cmd == "heading":
            self.editor.insert_heading()

    # ——— note commands
    def new_note(self, *_args, **fields) -> None:
        self.commit_editor()
        prev = self.current_id
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        kind = self.filter[0]
        if not fields:
            if kind == "tag":
                fields["Tags"] = [t for t in self.store.all_tags() if t.lower() == self.filter[1]]
            elif kind == "color":
                fields["Color"] = self.filter[1]
            elif kind == "pinned":
                fields["Pinned"] = True
            elif kind == "reminders":
                self.filter = ("all",)
        if len(self.store.notes) >= MAX_NOTES:
            QMessageBox.warning(self, "Micronotes", f"Limit of {MAX_NOTES} notes reached. Delete or export old notes first.")
            return
        n = new_note(**fields)
        self.store.notes.append(n)
        self.current_id = n["id"]
        self.drop_if_empty(prev)
        self.refresh_sidebar()
        self.refresh_list()
        self.show_note(n["id"])
        self.set_preview(False)
        self.title.setFocus()

    def duplicate_note(self) -> None:
        src = self.store.get(self.current_id)
        if not src:
            return
        self.commit_editor()
        fields = {k: v for k, v in src.items() if k not in ("id", "Time", "Created", "Reminded")}
        fields["Subject"] = (src["Subject"] + " copy")[:MAX_SUBJECT]
        self.new_note(**fields)
        self.dirty = True
        self.commit_editor()

    def delete_selected(self) -> None:
        self.commit_editor()
        ids = set(self.selected_ids())
        if not ids:
            return
        row = self.notes.currentRow()
        removed = [n for n in self.store.notes if n["id"] in ids]
        self.store.notes = [n for n in self.store.notes if n["id"] not in ids]
        if not self.save():
            self.store.notes.extend(removed)
            return
        real = [n for n in removed if not is_empty(n)]
        if real:
            self.undo_stack.append(real)
            del self.undo_stack[:-UNDO_DEPTH]
        self.current_id = None
        self.refresh_sidebar()
        self.refresh_list()
        if self.notes.count():
            self.notes.setCurrentRow(min(max(row, 0), self.notes.count() - 1))
        else:
            self.show_note(None)
        self.flash(f"Deleted {len(removed)} note{'s' if len(removed) != 1 else ''} — ⌘Z in the list to undo")

    def undo_delete(self) -> None:
        if not self.undo_stack:
            self.flash("Nothing to undo")
            return
        restored = self.undo_stack.pop()
        self.store.notes.extend(restored)
        if self.save():
            self.refresh_sidebar()
            self.refresh_list()
            self.select_ids([n["id"] for n in restored])
            self.flash(f"Restored {len(restored)}")

    def toggle_pin_selected(self) -> None:
        self.commit_editor()
        notes = [n for n in (self.store.get(i) for i in self.selected_ids()) if n]
        if not notes:
            return
        pin = not all(n["Pinned"] for n in notes)
        for n in notes:
            n["Pinned"] = pin
        self.save()
        self.loading = True
        self.btn_pin.setChecked(bool(self.store.get(self.current_id) and self.store.get(self.current_id)["Pinned"]))
        self.loading = False
        self.refresh_sidebar()
        self.refresh_list()

    def copy_notes(self) -> None:
        self.commit_editor()
        order = {self.notes.item(i).data(NOTE_ROLE): i for i in range(self.notes.count())}
        notes = sorted((n for n in (self.store.get(i) for i in self.selected_ids()) if n),
                       key=lambda n: order.get(n["id"], 0))
        if notes:
            QApplication.clipboard().setText("\n---\n\n".join(formats.note_as_markdown(n, 1) for n in notes))
            self.flash(f"Copied {len(notes)} as Markdown")

    def notes_menu(self, pos) -> None:
        it = self.notes.itemAt(pos)
        if it and not it.isSelected():
            self.notes.setCurrentItem(it)
        m = QMenu(self)
        has = bool(self.notes.selectedItems())
        for text, slot in (("Pin / Unpin", self.toggle_pin_selected), ("Duplicate", self.duplicate_note),
                           ("Copy as Markdown", self.copy_notes),
                           ("Export Selected…", lambda: self.export_notes(True))):
            m.addAction(text, slot).setEnabled(has)
        colors = m.addMenu("Color")
        colors.setEnabled(has)
        for c in COLORS:
            a = colors.addAction(c.capitalize() if c else "None", lambda c=c: self.color_selected(c))
            if c:
                a.setIcon(color_dot(c))
        m.addSeparator()
        m.addAction("Delete", self.delete_selected).setEnabled(has)
        if self.undo_stack:
            m.addAction("Undo Delete", self.undo_delete)
        m.exec(self.notes.viewport().mapToGlobal(pos))

    def color_selected(self, color: str) -> None:
        self.commit_editor()
        for nid in self.selected_ids():
            if n := self.store.get(nid):
                n["Color"] = color
        self.save()
        cur = self.store.get(self.current_id)
        if cur:
            self.loading = True
            self.color.set_color(cur["Color"])
            self.loading = False
        self.refresh_sidebar()
        self.refresh_list()

    def set_sort(self, key: str) -> None:
        self.sort_key = self.settings["sort"] = key
        self.refresh_list()

    def toggle_sidebar(self) -> None:
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self.act_sidebar.setChecked(self.sidebar.isVisible())

    # ——— reminders
    def check_reminders(self) -> None:
        due = due_reminders(self.store.notes)
        if not due:
            return
        for n in due:
            n["Reminded"] = True
            notify(n["Subject"] or "Micronotes reminder", plain_preview(n["Description"], 150) or "Reminder")
        self.save()
        QApplication.alert(self)
        cur = self.store.get(self.current_id)
        if any(cur is d for d in due):
            self.loading = True
            self._show_reminder(cur)
            self.loading = False
        self.refresh_sidebar()
        self.refresh_list()
        self.flash(f"Reminder: {due[0]['Subject'] or 'Untitled'}" + (f" (+{len(due) - 1} more)" if len(due) > 1 else ""))

    # ——— import / export
    def export_notes(self, selected_only: bool) -> None:
        self.commit_editor()
        if selected_only:
            ids = set(self.selected_ids())
            notes = [n for n in self.visible_notes() if n["id"] in ids]
        else:
            notes = sorted(self.store.notes, key=lambda n: n["Time"], reverse=True)
        notes = [n for n in notes if not is_empty(n)]
        if not notes:
            QMessageBox.information(self, "Micronotes", "Nothing to export.")
            return
        name = f"micronotes-{datetime.now():%Y-%m-%d}.md"
        if selected_only and len(notes) == 1 and notes[0]["Subject"]:
            name = re.sub(r'[\\/:*?"<>|]+', "-", notes[0]["Subject"])[:80] + ".md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export notes", str(Path.home() / "Desktop" / name),
            "Markdown (*.md);;Plain text (*.txt);;CSV (*.csv);;JSON (*.json);;HTML (*.html)")
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in formats.EXPORT_EXTS:
            p = p.with_suffix(".md")
        try:
            formats.export_notes(p, notes, md_to_html)
        except OSError as e:
            QMessageBox.critical(self, "Micronotes", f"Export failed:\n{e}")
            return
        self.flash(f"Exported {len(notes)} to {p.name}")

    def import_notes(self) -> None:
        self.commit_editor()
        exts = " ".join(f"*{e}" for e in formats.TEXT_EXTS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import notes", str(Path.home()),
            f"Supported files (*.json *.csv {exts});;JSON (*.json);;CSV (*.csv);;Text / Markdown ({exts})")
        if not paths:
            return
        raw: list = []
        errors: List[str] = []
        truncated = 0
        for path in paths:
            try:
                items, cut = formats.import_file(Path(path))
                raw += items
                truncated += cut
            except Exception as e:  # any malformed file is reported, not fatal
                errors.append(f"{Path(path).name}: {e}")
        imported = normalize_all(raw)
        for n in imported:
            n["id"] = new_note()["id"]
        room = MAX_NOTES - len(self.store.notes)
        if len(imported) > room:
            errors.append(f"Only {room} notes imported: limit of {MAX_NOTES} reached")
            imported = imported[:room]
        if imported:
            self.store.notes.extend(imported)
            if self.save():
                self.filter = ("all",)
                self.search.clear()
                self.refresh_sidebar()
                self.refresh_list()
                self.select_ids([n["id"] for n in imported])
        msg = f"Imported {len(imported)} note{'s' if len(imported) != 1 else ''}."
        if truncated:
            msg += f"\n{truncated} file(s) were longer than {MAX_DESC} characters and were truncated."
        if errors:
            QMessageBox.warning(self, "Micronotes", msg + "\n\nProblems:\n" + "\n".join(errors))
        elif truncated:
            QMessageBox.information(self, "Micronotes", msg)
        else:
            self.flash(msg)

    # ——— data location
    def use_icloud(self) -> None:
        d = icloud_data_dir()
        if d is None:
            QMessageBox.information(self, "Micronotes", "iCloud Drive is not enabled on this Mac.")
            self._watch()
            return
        self.switch_data_dir(d)

    def choose_data_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for notes", str(self.store.data_dir))
        if d:
            self.switch_data_dir(Path(d))
        else:
            self._watch()

    def switch_data_dir(self, new_dir: Path) -> None:
        self.commit_editor()
        new_dir = Path(new_dir)
        if new_dir.resolve() == self.store.data_dir.resolve():
            self._watch()
            return
        target = Store(new_dir)
        try:
            existing = read_notes_file(target.path)
        except (LoadError, OSError) as e:
            QMessageBox.critical(self, "Micronotes", f"Can't use {target.path}:\n{e}")
            self._watch()
            return
        mine = [n for n in self.store.notes if not is_empty(n)]
        if existing:
            text = (f"{len(existing)} notes already exist in\n{new_dir}\n\n"
                    f"They will be merged with your {len(mine)} notes (the newest version of each note wins).")
        else:
            text = f"Your {len(mine)} notes will be copied to\n{new_dir}"
        text += "\n\nThe copy in the current location is left untouched."
        if QMessageBox.question(self, "Change data location", text) != QMessageBox.StandardButton.Yes:
            self._watch()
            return
        target.notes = merge(existing, mine)
        try:
            target.save()
        except OSError as e:
            QMessageBox.critical(self, "Micronotes", f"Could not write to {new_dir}:\n{e}")
            self._watch()
            return
        self.store = target
        if new_dir == default_data_dir():
            self.settings.pop("data_dir", None)
        else:
            self.settings["data_dir"] = str(new_dir)
        self.settings.save()
        self._watch()
        self.refresh_sidebar()
        self.refresh_list(select_first=True)
        self.flash(f"Notes are now stored in {new_dir}")

    def show_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_dir)))
