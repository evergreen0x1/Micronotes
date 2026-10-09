"""Small Markdown helpers used by the editor and the list (no Qt)."""
from __future__ import annotations

import re
from typing import Optional

TASK_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\])")
LIST_RE = re.compile(r"^(\s*)([-*+]|(\d+)([.)]))(\s+)(\[[ xX]\]\s+)?")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def toggle_task(source: str, index: int) -> str:
    """Toggles the index-th task checkbox ("- [ ]" / "- [x]"), ignoring fenced code."""
    lines = source.split("\n")
    in_code = False
    k = 0
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = TASK_RE.match(line)
        if not m:
            continue
        if k == index:
            mark = " " if m.group(2) in "xX" else "x"
            lines[i] = m.group(1) + mark + m.group(3) + line[m.end():]
            return "\n".join(lines)
        k += 1
    return source


def continue_list(line: str) -> Optional[str]:
    """For Enter at the end of a list line returns the prefix for the next line.

    Returns "" when the line is an empty list item (the item should be removed),
    None when the line is not a list item.
    """
    m = LIST_RE.match(line)
    if not m:
        return None
    if not line[m.end():].strip():
        return ""
    indent, bullet, num, delim, space, task = m.groups()
    if num is not None:
        bullet = f"{int(num) + 1}{delim}"
    return f"{indent}{bullet}{space}{'[ ] ' if task else ''}"


def task_counts(source: str) -> tuple[int, int]:
    done = total = 0
    in_code = False
    for line in source.split("\n"):
        if FENCE_RE.match(line):
            in_code = not in_code
            continue
        m = None if in_code else TASK_RE.match(line)
        if m:
            total += 1
            done += m.group(2) in "xX"
    return done, total


_INLINE = [
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])"), r"\2"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
]


def plain_preview(source: str, limit: int = 200) -> str:
    """One-line plain text preview of a Markdown note for the notes list."""
    parts = []
    size = 0
    for line in source.split("\n"):
        s = line.strip()
        if not s or FENCE_RE.match(s) or re.fullmatch(r"[-*_]{3,}", s):
            continue
        task = TASK_RE.match(s)
        if task:
            s = ("☑ " if task.group(2) in "xX" else "☐ ") + s[task.end():].strip()
        else:
            s = re.sub(r"^(#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", s)
        for rx, rep in _INLINE:
            s = rx.sub(rep, s)
        parts.append(s)
        size += len(s)
        if size > limit:
            break
    return "  ".join(parts)[:limit]
