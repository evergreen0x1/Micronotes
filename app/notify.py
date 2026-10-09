"""System notifications for reminders."""
from __future__ import annotations

import subprocess
import sys

_SCRIPT = [
    "on run argv",
    'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
    "end run",
]


def notify(title: str, body: str) -> bool:
    """Shows a macOS notification. Text goes through argv, so it is never parsed as AppleScript."""
    if sys.platform != "darwin":
        return False
    args = ["osascript"]
    for line in _SCRIPT:
        args += ["-e", line]
    try:
        subprocess.Popen(args + [title[:200], body[:400]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
