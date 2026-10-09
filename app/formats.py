"""Import / export of notes in text formats (no Qt)."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .storage import MAX_DESC, Note, parse_tags

MAX_IMPORT_SIZE = 5 * 1024 * 1024
TEXT_EXTS = (".txt", ".md", ".markdown", ".text", ".log", ".rst", ".org")
EXPORT_EXTS = (".md", ".txt", ".csv", ".json", ".html")
TEXT_ENCODINGS = ("utf-8-sig", "cp1251", "latin-1")

COLOR_HEX = {
    "red": "#FF453A", "orange": "#FF9F0A", "yellow": "#FFD60A", "green": "#30D158",
    "blue": "#0A84FF", "purple": "#BF5AF2", "gray": "#8E8E93",
}

CSV_ALIASES = {
    "Subject": ("subject", "title", "name", "тема", "заголовок"),
    "Tags": ("tags", "tag", "info", "additional info", "category", "теги", "инфо"),
    "Description": ("description", "text", "body", "content", "note", "описание", "текст"),
    "Created": ("created", "created at", "date", "дата"),
    "Time": ("updated", "time", "modified", "updated at"),
    "Color": ("color", "colour", "цвет"),
    "Pinned": ("pinned",),
    "Remind": ("remind", "reminder", "напоминание"),
}


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ——— export

def note_as_text(n: Note) -> str:
    head = n["Subject"] or "Untitled"
    meta = " · ".join(x for x in (" ".join("#" + t for t in n["Tags"]), n["Time"]) if x)
    return "\n".join(x for x in (head, meta, n["Description"]) if x)


def note_as_markdown(n: Note, level: int = 2) -> str:
    out = [f"{'#' * level} {'📌 ' if n['Pinned'] else ''}{n['Subject'] or 'Untitled'}", ""]
    meta = [" ".join("#" + t.replace(" ", "_") for t in n["Tags"]), f"Updated {n['Time']}"]
    if n["Remind"]:
        meta.append(f"Reminder {n['Remind']}")
    out += ["_" + " · ".join(m for m in meta if m) + "_", ""]
    if n["Description"]:
        out += [n["Description"], ""]
    return "\n".join(out)


def to_markdown(notes: List[Note]) -> str:
    head = f"# Micronotes\n\n_Exported {datetime.now():%Y-%m-%d %H:%M}_\n"
    return head + "\n" + "\n---\n\n".join(note_as_markdown(n) for n in notes)


def to_html(notes: List[Note], md_to_html: Optional[Callable[[str], str]] = None) -> str:
    cards = []
    for n in notes:
        body = md_to_html(n["Description"]) if md_to_html else \
            "<p>" + escape(n["Description"]).replace("\n", "<br>") + "</p>"
        tags = "".join(f"<span class=tag>#{escape(t)}</span>" for t in n["Tags"])
        color = COLOR_HEX.get(n["Color"], "transparent")
        cards.append(
            f"<article style='border-left-color:{color}'>"
            f"<h2>{'📌 ' if n['Pinned'] else ''}{escape(n['Subject'] or 'Untitled')}</h2>"
            f"<p class=meta>{tags} <span>{escape(n['Time'])}</span></p>{body}</article>")
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'><title>Micronotes</title>"
        "<style>:root{--bg:#F2F2F7;--card:#fff;--text:#111;--muted:#6e6e73;--line:#e0e0e5;--accent:#0A84FF}"
        "@media(prefers-color-scheme:dark){:root{--bg:#1C1C1E;--card:#2C2C2E;--text:#F2F2F7;"
        "--muted:#98989E;--line:#3A3A3C}}"
        "body{font:15px/1.55 -apple-system,system-ui,sans-serif;max-width:760px;margin:40px auto;"
        "padding:0 16px;color:var(--text);background:var(--bg)}"
        "article{background:var(--card);border-radius:12px;padding:16px 20px;margin:14px 0;"
        "border:1px solid var(--line);border-left:4px solid transparent}"
        "h1{font-weight:600}h2{margin:0 0 4px;font-size:18px}.meta{color:var(--muted);font-size:13px;margin:0 0 8px}"
        ".tag{color:var(--accent);margin-right:6px}a{color:var(--accent)}"
        "pre,code{background:rgba(127,127,127,.15);border-radius:4px;padding:1px 4px}</style>"
        f"<h1>Micronotes</h1>{''.join(cards)}</html>")


def to_csv(notes: List[Note]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Created", "Updated", "Subject", "Tags", "Color", "Pinned", "Remind", "Description"])
    for n in notes:
        w.writerow([n["Created"], n["Time"], n["Subject"], ", ".join(n["Tags"]), n["Color"],
                    "yes" if n["Pinned"] else "", n["Remind"], n["Description"]])
    return buf.getvalue()


def export_notes(path: Path, notes: List[Note], md_to_html: Optional[Callable[[str], str]] = None) -> None:
    ext = path.suffix.lower()
    if ext == ".json":
        text, enc = json.dumps(notes, ensure_ascii=False, indent=2), "utf-8"
    elif ext == ".csv":
        text, enc = to_csv(notes), "utf-8-sig"  # BOM so Excel detects UTF-8
    elif ext in (".html", ".htm"):
        text, enc = to_html(notes, md_to_html), "utf-8"
    elif ext in (".md", ".markdown"):
        text, enc = to_markdown(notes), "utf-8"
    else:
        text, enc = "\n\n".join(note_as_text(n) for n in notes) + "\n", "utf-8"
    path.write_text(text, encoding=enc, newline="")


# ——— import

def import_json(text: str) -> list:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("notes", [data])
    if not isinstance(data, list):
        raise ValueError("expected a list of notes")
    return data


def import_csv(text: str) -> list:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    cols = {f: next((i for i, h in enumerate(header) if h in names), None) for f, names in CSV_ALIASES.items()}
    if cols["Subject"] is None and cols["Description"] is None:
        raise ValueError("no Subject/Title or Description/Text column found")
    out = []
    for row in rows[1:]:
        n = {f: (row[i].strip() if i is not None and i < len(row) else "") for f, i in cols.items()}
        n["Pinned"] = n["Pinned"].lower() in ("yes", "true", "1")
        if n["Subject"] or n["Description"] or n["Tags"]:
            out.append(n)
    return out


_META_RE = re.compile(r"^_(.*)_$")


def import_markdown(text: str, fallback_title: str) -> list:
    """A Micronotes Markdown export is split back into notes; any other file is one note
    whose title is its first heading (or the file name)."""
    lines = text.strip("\ufeff").split("\n")
    if lines and lines[0].strip() == "# Micronotes" and any(l.startswith("## ") for l in lines):
        notes, cur = [], None
        for line in lines:
            if line.startswith("## "):
                cur = {"Subject": line[3:].strip().removeprefix("📌 ").strip(),
                       "Pinned": line[3:].startswith("📌"), "body": []}
                notes.append(cur)
            elif cur is not None:
                cur["body"].append(line)
        out = []
        for n in notes:
            body = n.pop("body")
            while body and not body[0].strip():
                body.pop(0)
            if body and (m := _META_RE.match(body[0].strip())):
                meta = m.group(1)
                n["Tags"] = [t.replace("_", " ") for t in re.findall(r"#(\S+)", meta)]
                if r := re.search(r"Reminder (\d{4}-\d\d-\d\d \d\d:\d\d)", meta):
                    n["Remind"] = r.group(1)
                body.pop(0)
            while body and body[-1].strip() in ("", "---"):
                body.pop()
            n["Description"] = "\n".join(body).strip()
            out.append(n)
        return out
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is not None and re.match(r"#\s+\S", lines[first]):
        title = lines[first].lstrip("#").strip()
        return [{"Subject": title, "Description": "\n".join(lines[first + 1:]).strip()}]
    return [{"Subject": fallback_title, "Description": text.strip()}]


def import_file(path: Path) -> Tuple[list, bool]:
    """Returns (raw notes, truncated?). Raises on unreadable/unsupported content."""
    if path.stat().st_size > MAX_IMPORT_SIZE:
        raise ValueError("file is larger than 5 MB")
    text = read_text_file(path)
    ext = path.suffix.lower()
    if ext == ".json":
        items = import_json(text)
    elif ext == ".csv":
        items = import_csv(text)
    elif ext in (".md", ".markdown"):
        items = import_markdown(text, path.stem)
    else:
        items = [{"Subject": path.stem, "Description": text.strip()}]
    truncated = any(isinstance(i, dict) and len(str(i.get("Description", ""))) > MAX_DESC for i in items)
    for i in items:
        if isinstance(i, dict) and "Tags" in i:
            i["Tags"] = parse_tags(i["Tags"])
    return items, truncated
