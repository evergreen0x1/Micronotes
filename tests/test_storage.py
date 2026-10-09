import json
from datetime import datetime

from app import storage as S


def test_v1_note_is_migrated():
    n = S.normalize({"id": "a", "Time": "2026-01-02 03:04:05", "Subject": "Hi",
                     "Info": "home, #work, home", "Description": "x"})
    assert n["Tags"] == ["home", "work"]
    assert n["Created"] == n["Time"] == "2026-01-02 03:04:05"
    assert n["Color"] == "" and n["Pinned"] is False and n["Remind"] == ""


def test_invalid_values_are_cleaned():
    n = S.normalize({"Time": "garbage", "Color": "neon", "Remind": "tomorrow", "Subject": "x" * 500})
    assert S.parse_time(n["Time"]) and n["Color"] == "" and n["Remind"] == ""
    assert len(n["Subject"]) == S.MAX_SUBJECT
    assert S.normalize("nope") is None


def test_store_roundtrip_and_backup(tmp_path):
    st = S.Store(tmp_path)
    st.notes = [S.new_note(Subject="one")]
    st.save()
    st.notes.append(S.new_note(Subject="two"))
    st.save()
    assert (tmp_path / S.BACKUP_FILE).exists()
    st2 = S.Store(tmp_path)
    assert st2.load() is None and [n["Subject"] for n in st2.notes] == ["one", "two"]


def test_broken_file_is_preserved(tmp_path):
    (tmp_path / S.NOTES_FILE).write_text("{broken")
    st = S.Store(tmp_path)
    warning = st.load()
    assert warning and st.notes == []
    assert list(tmp_path.glob("notes.broken-*.json"))
    assert (tmp_path / S.NOTES_FILE).read_text() == "{broken"


def test_duplicate_ids_are_fixed(tmp_path):
    (tmp_path / S.NOTES_FILE).write_text(json.dumps([{"id": "x", "Subject": "a"}, {"id": "x", "Subject": "b"}]))
    st = S.Store(tmp_path)
    st.load()
    assert len({n["id"] for n in st.notes}) == 2


def test_merge_keeps_newest():
    a = S.normalize({"id": "1", "Time": "2026-01-01 00:00:00", "Subject": "old"})
    b = S.normalize({"id": "1", "Time": "2026-02-01 00:00:00", "Subject": "new"})
    c = S.normalize({"id": "2", "Subject": "other"})
    merged = S.merge([a], [b, c])
    assert {n["Subject"] for n in merged} == {"new", "other"}
    assert S.merge([b], [a])[0]["Subject"] == "new"


def test_due_reminders():
    n1 = S.normalize({"Subject": "a", "Remind": "2026-01-01 10:00"})
    n2 = S.normalize({"Subject": "b", "Remind": "2026-01-01 12:00"})
    n3 = S.normalize({"Subject": "c", "Remind": "2026-01-01 09:00", "Reminded": True})
    assert S.due_reminders([n1, n2, n3], datetime(2026, 1, 1, 11)) == [n1]


def test_tags_and_settings(tmp_path):
    assert S.parse_tags(" #a ,b,, A ,  c  d ") == ["a", "b", "c d"]
    st = S.Settings(tmp_path / "s.json")
    assert st.data_dir() == S.default_data_dir()
    st["data_dir"] = str(tmp_path)
    st.save()
    assert S.Settings(tmp_path / "s.json").data_dir() == tmp_path
