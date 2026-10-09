"""Notes storage: schema normalization, atomic JSON persistence, settings, data locations.

Pure Python (no Qt) so it can be unit-tested.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

APP_NAME = "micronotes"
NOTES_FILE = "notes.json"
SETTINGS_FILE = "settings.json"
BACKUP_FILE = "notes.backup.json"

MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_NOTES = 10000
MAX_SUBJECT = 200
MAX_DESC = 100_000
MAX_TAGS = 20
MAX_TAG_LEN = 40

TIME_FMT = "%Y-%m-%d %H:%M:%S"
REMIND_FMT = "%Y-%m-%d %H:%M"

# "" = no colour label
COLORS = ("", "red", "orange", "yellow", "green", "blue", "purple", "gray")

IS_MAC = platform.system() == "Darwin"

Note = Dict[str, Any]


def now() -> str:
    return datetime.now().strftime(TIME_FMT)


def parse_time(value: str, fmt: str = TIME_FMT) -> Optional[datetime]:
    try:
        return datetime.strptime(value, fmt)
    except (TypeError, ValueError):
        return None


# ——— locations

def default_data_dir() -> Path:
    home = Path.home()
    return home / "Library/Application Support" / APP_NAME if IS_MAC else home / f".{APP_NAME}"


def icloud_root() -> Optional[Path]:
    p = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
    return p if p.is_dir() else None


def icloud_data_dir() -> Optional[Path]:
    root = icloud_root()
    return root / "Micronotes" if root else None


# ——— schema

def parse_tags(value: Any) -> List[str]:
    """Accepts a list or a comma separated string; strips '#', dedupes case-insensitively."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = str(value or "").split(",")
    out: List[str] = []
    seen = set()
    for p in parts:
        t = re.sub(r"\s+", " ", p.strip().lstrip("#").strip())[:MAX_TAG_LEN]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TAGS]


def normalize(raw: Any) -> Optional[Note]:
    """Brings a note from any known version of the file format to the current schema.

    v1 (Tkinter) notes had a free-text "Info" field; it becomes the tag list.
    """
    if not isinstance(raw, dict):
        return None
    time = str(raw.get("Time") or "") or now()
    if parse_time(time) is None:
        time = now()
    created = str(raw.get("Created") or "")
    if parse_time(created) is None:
        created = time
    color = str(raw.get("Color") or "").lower()
    remind = str(raw.get("Remind") or "")
    if parse_time(remind, REMIND_FMT) is None:
        remind = ""
    tags = raw.get("Tags")
    if tags is None:
        tags = raw.get("Info", "")
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "Created": created,
        "Time": time,
        "Subject": str(raw.get("Subject") or "")[:MAX_SUBJECT],
        "Tags": parse_tags(tags),
        "Color": color if color in COLORS else "",
        "Description": str(raw.get("Description") or "")[:MAX_DESC],
        "Pinned": bool(raw.get("Pinned", False)),
        "Remind": remind,
        "Reminded": bool(raw.get("Reminded", False)) if remind else False,
    }


def new_note(**fields: Any) -> Note:
    t = now()
    n = normalize({"id": uuid.uuid4().hex, "Time": t, "Created": t, **fields})
    assert n is not None
    return n


def is_empty(n: Note) -> bool:
    """No title and no text (tags/colour alone don't make a note worth keeping)."""
    return not (n["Subject"].strip() or n["Description"].strip())


def normalize_all(items: Iterable[Any]) -> List[Note]:
    out: List[Note] = []
    seen = set()
    for raw in items:
        n = normalize(raw)
        if n is None:
            continue
        if n["id"] in seen:
            n["id"] = uuid.uuid4().hex
        seen.add(n["id"])
        out.append(n)
        if len(out) >= MAX_NOTES:
            break
    return out


def merge(a: List[Note], b: List[Note]) -> List[Note]:
    """Union by id; when both sides have a note, the more recently updated one wins."""
    by_id: Dict[str, Note] = {n["id"]: n for n in a}
    for n in b:
        cur = by_id.get(n["id"])
        if cur is None or n["Time"] > cur["Time"]:
            by_id[n["id"]] = n
    return list(by_id.values())[:MAX_NOTES]


def due_reminders(notes: Iterable[Note], at: Optional[datetime] = None) -> List[Note]:
    at = at or datetime.now()
    out = []
    for n in notes:
        if n["Remind"] and not n["Reminded"]:
            dt = parse_time(n["Remind"], REMIND_FMT)
            if dt and dt <= at:
                out.append(n)
    return out


def next_full_hour(at: Optional[datetime] = None) -> datetime:
    at = at or datetime.now()
    return at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


# ——— persistence

class LoadError(Exception):
    pass


def read_notes_file(path: Path) -> List[Note]:
    if not path.exists():
        return []
    if path.stat().st_size > MAX_FILE_SIZE:
        raise LoadError("file is larger than 20 MB")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise LoadError(f"file is not valid JSON ({e})") from e
    if not isinstance(data, list):
        raise LoadError("unexpected file format")
    return normalize_all(data)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Store:
    """Notes file in a data folder. Keeps one backup per session and never overwrites
    a file it could not read."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.notes: List[Note] = []
        self.backup_done = False
        self.last_mtime: Optional[float] = None

    @property
    def path(self) -> Path:
        return self.data_dir / NOTES_FILE

    def mtime(self) -> Optional[float]:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def load(self) -> Optional[str]:
        """Loads notes; returns a warning message if the file was unreadable."""
        try:
            self.notes = read_notes_file(self.path)
            self.last_mtime = self.mtime()
            return None
        except (LoadError, OSError) as e:
            self.notes = []
            backup = self.path.with_name(f"notes.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                shutil.copy2(self.path, backup)
                where = f"A copy was saved to:\n{backup}"
            except OSError:
                where = "Could not create a backup copy."
            return f"Could not read notes ({e}).\n{where}"

    def save(self) -> None:
        """Raises OSError on failure."""
        if not self.backup_done and self.path.exists():
            shutil.copy2(self.path, self.path.with_name(BACKUP_FILE))
            self.backup_done = True
        write_json_atomic(self.path, self.notes)
        self.last_mtime = self.mtime()

    def get(self, nid: Optional[str]) -> Optional[Note]:
        if not nid:
            return None
        for n in self.notes:
            if n["id"] == nid:
                return n
        return None

    def all_tags(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        canonical: Dict[str, str] = {}
        for n in self.notes:
            for t in n["Tags"]:
                key = canonical.setdefault(t.lower(), t)
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[0].lower()))


class Settings(dict):
    """Per-machine settings; always stored locally, never in a synced folder."""

    def __init__(self, path: Optional[Path] = None):
        super().__init__()
        self.path = path or default_data_dir() / SETTINGS_FILE
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.update(data)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            write_json_atomic(self.path, dict(self))
        except OSError:
            pass

    def data_dir(self) -> Path:
        d = self.get("data_dir")
        return Path(d) if isinstance(d, str) and d else default_data_dir()
