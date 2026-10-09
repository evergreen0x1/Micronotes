import json

from app import formats as F
from app import mdtools as M
from app import storage as S


def notes():
    return [S.new_note(Subject="Shop", Tags=["home", "to do"], Description="- [ ] milk\n- [x] bread\n\n**bold**",
                       Pinned=True, Color="green", Remind="2026-10-11 09:00"),
            S.new_note(Subject="Идея", Description="Строка 1\nСтрока 2")]


def test_roundtrip_all_formats(tmp_path):
    src = notes()
    for ext in (".json", ".csv", ".md"):
        p = tmp_path / f"out{ext}"
        F.export_notes(p, src)
        items, cut = F.import_file(p)
        back = S.normalize_all(items)
        assert not cut and len(back) == 2, ext
        by = {n["Subject"].lstrip("📌 "): n for n in back}
        assert by["Shop"]["Tags"] == ["home", "to do"], ext
        assert by["Shop"]["Description"] == src[0]["Description"], ext
        assert by["Shop"]["Pinned"] and by["Shop"]["Remind"] == "2026-10-11 09:00", ext
        assert by["Идея"]["Description"] == "Строка 1\nСтрока 2", ext
    for ext in (".txt", ".html"):
        F.export_notes(tmp_path / f"out{ext}", src)
        assert "Идея" in (tmp_path / f"out{ext}").read_text(encoding="utf-8")


def test_csv_excel_bom_and_semicolons(tmp_path):
    F.export_notes(tmp_path / "x.csv", notes())
    assert (tmp_path / "x.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    (tmp_path / "s.csv").write_text("Заголовок;Текст;Теги\nA;b;x, y\n", encoding="cp1251")
    items, _ = F.import_file(tmp_path / "s.csv")
    assert items[0]["Subject"] == "A" and items[0]["Tags"] == ["x", "y"]


def test_text_files(tmp_path):
    (tmp_path / "plain.txt").write_bytes("Привет".encode("cp1251"))
    (tmp_path / "doc.md").write_text("# Title\n\nBody", encoding="utf-8")
    assert F.import_file(tmp_path / "plain.txt")[0] == [{"Subject": "plain", "Description": "Привет"}]
    assert F.import_file(tmp_path / "doc.md")[0] == [{"Subject": "Title", "Description": "Body"}]
    (tmp_path / "bad.json").write_text("{}x")
    try:
        F.import_file(tmp_path / "bad.json")
        assert False
    except json.JSONDecodeError:
        pass


def test_toggle_task_skips_code():
    src = "- [ ] a\n```\n- [ ] code\n```\n1. [x] b"
    assert M.toggle_task(src, 0).startswith("- [x] a")
    assert M.toggle_task(src, 1).endswith("1. [ ] b")
    assert "- [ ] code" in M.toggle_task(src, 1)
    assert M.task_counts(src) == (1, 2)


def test_continue_list():
    assert M.continue_list("- item") == "- "
    assert M.continue_list("  - [x] done") == "  - [ ] "
    assert M.continue_list("9. nine") == "10. "
    assert M.continue_list("- ") == ""
    assert M.continue_list("text") is None


def test_plain_preview():
    assert M.plain_preview("# Head\n- [x] **done** [link](http://x)\n`c`") == "Head  ☑ done link  c"
