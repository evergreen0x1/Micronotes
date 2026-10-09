"""Draws the app icon and writes assets/icon.png + assets/micronotes.icns (macOS iconutil).

Run: .venv/bin/python tools/make_icon.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def draw(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 1024

    # macOS-style rounded square with a soft shadow
    body = QRectF(100 * s, 100 * s, 824 * s, 824 * s)
    shadow = QPainterPath()
    shadow.addRoundedRect(body.translated(0, 12 * s), 185 * s, 185 * s)
    p.fillPath(shadow, QColor(0, 0, 0, 60))
    bg = QPainterPath()
    bg.addRoundedRect(body, 185 * s, 185 * s)
    g = QLinearGradient(body.topLeft(), body.bottomRight())
    g.setColorAt(0, QColor("#4FA8FF"))
    g.setColorAt(1, QColor("#0A5BD6"))
    p.fillPath(bg, g)

    # note card with a folded corner
    card = QRectF(250 * s, 215 * s, 524 * s, 594 * s)
    fold = 120 * s
    path = QPainterPath()
    path.moveTo(card.left() + 40 * s, card.top())
    path.lineTo(card.right() - fold, card.top())
    path.lineTo(card.right(), card.top() + fold)
    path.lineTo(card.right(), card.bottom() - 40 * s)
    path.quadTo(card.right(), card.bottom(), card.right() - 40 * s, card.bottom())
    path.lineTo(card.left() + 40 * s, card.bottom())
    path.quadTo(card.left(), card.bottom(), card.left(), card.bottom() - 40 * s)
    path.lineTo(card.left(), card.top() + 40 * s)
    path.quadTo(card.left(), card.top(), card.left() + 40 * s, card.top())
    p.fillPath(path, QColor("#FFFFFF"))
    corner = QPainterPath()
    corner.moveTo(card.right() - fold, card.top())
    corner.lineTo(card.right() - fold, card.top() + fold - 24 * s)
    corner.quadTo(card.right() - fold, card.top() + fold, card.right() - fold + 24 * s, card.top() + fold)
    corner.lineTo(card.right(), card.top() + fold)
    corner.closeSubpath()
    p.fillPath(corner, QColor("#D6E6FB"))

    # checklist rows
    x0 = card.left() + 70 * s
    for i, (done, width) in enumerate(((True, 250), (True, 200), (False, 230))):
        y = card.top() + 165 * s + i * 135 * s
        box = QRectF(x0, y - 34 * s, 68 * s, 68 * s)
        if done:
            bp = QPainterPath()
            bp.addRoundedRect(box, 18 * s, 18 * s)
            p.fillPath(bp, QColor("#30C35A"))
            pen = QPen(QColor("#FFFFFF"), 13 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([QPointF(box.left() + 17 * s, box.center().y() + 1 * s),
                            QPointF(box.left() + 30 * s, box.center().y() + 14 * s),
                            QPointF(box.right() - 15 * s, box.top() + 20 * s)])
        else:
            p.setPen(QPen(QColor("#B8C4D6"), 9 * s))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(4 * s, 4 * s, -4 * s, -4 * s), 16 * s, 16 * s)
        p.setPen(Qt.PenStyle.NoPen)
        line = QPainterPath()
        line.addRoundedRect(QRectF(x0 + 105 * s, y - 13 * s, width * s, 26 * s), 13 * s, 13 * s)
        p.fillPath(line, QColor("#C9D3E1" if done else "#7D8BA1"))
    p.end()
    return img


def main() -> int:
    app = QGuiApplication(sys.argv)  # required before painting
    ASSETS.mkdir(exist_ok=True)
    big = draw(1024)
    big.save(str(ASSETS / "icon.png"))
    if not shutil.which("iconutil"):
        print("iconutil not found (macOS only); wrote assets/icon.png")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "micronotes.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            draw(px).save(str(iconset / f"icon_{px}x{px}.png"))
            draw(px * 2).save(str(iconset / f"icon_{px}x{px}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "micronotes.icns")], check=True)
    print("wrote assets/icon.png and assets/micronotes.icns")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
