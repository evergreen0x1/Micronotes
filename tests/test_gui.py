"""Drives the real window offscreen (QT_QPA_PLATFORM=offscreen)."""
import json
from unittest import mock

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import storage as S  # noqa: E402
from app.widgets import NOTE_ROLE  # noqa: E402


@pytest.fixture
def win(isolated_home):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from app.window import MainWindow
    w = MainWindow(S.Settings())
    w.show()
    yield w
    w.persist()
    w.close()


def disk(w):
    return json.loads(w.store.path.read_text(encoding="utf-8"))


def type_note(w, title, body="", tags=""):
    w.new_note()
    QTest.keyClicks(w.title, title)
    if tags:
        QTest.keyClicks(w.tags, tags)
    w.editor.setFocus()
    QTest.keyClicks(w.editor, body)
    w.commit_editor()


def test_create_edit_autosave(win):
    type_note(win, "Groceries", "milk", "home, shop")
    assert [n["Subject"] for n in disk(win)] == ["Groceries"]
    assert disk(win)[0]["Tags"] == ["home", "shop"]
    assert win.notes.count() == 1
    # debounce timer saves without explicit commit
    QTest.keyClicks(win.editor, " and bread")
    QTest.qWait(900)
    assert disk(win)[0]["Description"] == "milk and bread"


def test_empty_new_note_is_discarded(win):
    type_note(win, "Keep", "x")
    keep = win.store.notes[0]["id"]
    win.new_note()
    win.new_note()
    win.select_ids([keep])
    assert [n["Subject"] for n in win.store.notes] == ["Keep"]


def test_list_continuation_and_checklist(win):
    win.new_note()
    win.editor.setFocus()
    QTest.keyClicks(win.editor, "- [ ] one")
    QTest.keyClick(win.editor, Qt.Key.Key_Return)
    QTest.keyClicks(win.editor, "two")
    QTest.keyClick(win.editor, Qt.Key.Key_Return)
    QTest.keyClick(win.editor, Qt.Key.Key_Return)  # empty item ends the list
    assert win.editor.toPlainText() == "- [ ] one\n- [ ] two\n"
    win.set_preview(True)
    win.on_task_toggled(1)
    assert win.editor.toPlainText() == "- [ ] one\n- [x] two\n"
    assert win.store.get(win.current_id)["Description"] == "- [ ] one\n- [x] two\n"


def test_filters_search_pin_color(win):
    type_note(win, "A", "alpha", "work")
    type_note(win, "B", "beta", "home")
    type_note(win, "C", "gamma")
    win.search.setText("#wo")
    assert win.notes.count() == 1
    win.search.setText("beta")
    assert win.notes.count() == 1
    win.search.clear()
    rows = {win.side_list.item(i).text(): i for i in range(win.side_list.count())}
    assert "# home" in rows and "# work" in rows
    win.side_list.setCurrentRow(rows["# home"])
    assert win.notes.count() == 1
    win.side_list.setCurrentRow(1)  # All
    assert win.notes.count() == 3
    last = win.notes.item(2).data(NOTE_ROLE)
    win.notes.setCurrentRow(2)
    win.toggle_pin_selected()
    assert win.notes.item(0).data(NOTE_ROLE) == last
    win.color_selected("red")
    assert win.store.get(last)["Color"] == "red"


def test_delete_and_undo(win):
    type_note(win, "A", "a")
    type_note(win, "B", "b")
    win.notes.setFocus()
    win.notes.setCurrentRow(0)
    QTest.keyClick(win.notes, Qt.Key.Key_Backspace)
    assert len(disk(win)) == 1
    win.undo_delete()
    assert len(disk(win)) == 2
    # Backspace inside the editor never deletes notes
    win.editor.setFocus()
    QTest.keyClick(win.editor, Qt.Key.Key_Backspace)
    assert len(win.store.notes) == 2


def test_reminder_fires(win):
    type_note(win, "Call", "mom")
    with mock.patch("app.window.notify") as notify:
        win.btn_remind.setChecked(True)
        n = win.store.get(win.current_id)
        assert n["Remind"]
        n["Remind"] = "2000-01-01 00:00"
        win.check_reminders()
        notify.assert_called_once()
    assert disk(win)[0]["Reminded"] is True


def test_external_change_is_picked_up(win):
    type_note(win, "Local", "x")
    data = disk(win)
    data.append(S.new_note(Subject="From other Mac"))
    S.write_json_atomic(win.store.path, data)
    win.on_external_change()
    assert {n["Subject"] for n in win.store.notes} == {"Local", "From other Mac"}


def test_switch_data_dir_merges(win, tmp_path):
    type_note(win, "Mine", "x")
    other = tmp_path / "cloud"
    S.write_json_atomic(other / S.NOTES_FILE, [S.new_note(Subject="Theirs")])
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        win.switch_data_dir(other)
    assert {n["Subject"] for n in disk(win)} == {"Mine", "Theirs"}
    assert win.settings["data_dir"] == str(other)


def test_import_export(win, tmp_path):
    type_note(win, "Exp", "**b**", "t")
    out = tmp_path / "e.html"
    with mock.patch("app.window.QFileDialog.getSaveFileName", return_value=(str(out), "")):
        win.export_notes(False)
    assert "<b>b</b>" in out.read_text() or "font-weight" in out.read_text()
    src = tmp_path / "in.md"
    src.write_text("# Imported\n\n- [ ] x")
    with mock.patch("app.window.QFileDialog.getOpenFileNames", return_value=([str(src)], "")):
        win.import_notes()
    assert "Imported" in {n["Subject"] for n in disk(win)}


def test_theme_switch(win):
    for mode in ("dark", "light", "system"):
        win.set_theme(mode)
    assert win.settings["theme"] == "system"
