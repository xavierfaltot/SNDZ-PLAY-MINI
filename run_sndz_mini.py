#!/usr/bin/env python3
"""Launch SONO PLAY MINI from the source checkout or frozen macOS app."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sndz_play_mini.global_bpm import install as install_global_bpm  # noqa: E402

install_global_bpm()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import sndz_play_mini.ui as ui  # noqa: E402


def _logo_path() -> Path:
    """Find the logo from source, PyInstaller temp data, or the macOS bundle."""
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        contents = executable.parent.parent
        candidates.append(contents / "Resources" / "sono_play_mini_logo.png")

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen_root = Path(meipass)
        candidates.extend(
            [
                frozen_root / "sndz_play_mini" / "assets" / "sono_play_mini_logo.png",
                frozen_root / "assets" / "sono_play_mini_logo.png",
                frozen_root / "sono_play_mini_logo.png",
            ]
        )

    candidates.extend(
        [
            ROOT / "src" / "sndz_play_mini" / "assets" / "sono_play_mini_logo.png",
            Path(ui.__file__).resolve().parent / "assets" / "sono_play_mini_logo.png",
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return candidates[0]


class BuiltInSonoLogo(ui.ClickableLogo):
    """Draw the SONO / PLAY / MINI mark directly in Qt.

    This removes the UI's dependency on an external PNG at runtime, so the
    packaged app looks the same on another Mac even if PyInstaller relocates
    resources inside the bundle.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__("")

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        words = ("SONO", "PLAY", "MINI")
        rows = len(words)
        cols = 4
        gap = max(1, int(min(self.width(), self.height()) * 0.012))
        cell_w = (self.width() - gap * (cols - 1)) / cols
        cell_h = (self.height() - gap * (rows - 1)) / rows

        font = QFont("Arial Narrow")
        font.setBold(True)
        font.setPixelSize(max(12, int(cell_h * 0.62)))
        painter.setFont(font)
        painter.setPen(QPen(QColor("#080808"), 1))

        for row, word in enumerate(words):
            for col, letter in enumerate(word):
                x = int(round(col * (cell_w + gap)))
                y = int(round(row * (cell_h + gap)))
                w = int(round(cell_w))
                h = int(round(cell_h))
                tile = QColor("#c22922") if row == 1 else QColor("#d8d0c0")
                painter.fillRect(x, y, w, h, tile)
                painter.drawText(x, y, w, h, Qt.AlignCenter, letter)

        painter.end()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(ui.APP_NAME)
    app.setOrganizationName("RUSH OPERATOR")

    logo_path = _logo_path()
    if logo_path.is_file():
        app.setWindowIcon(QIcon(str(logo_path)))

    window = ui.SonoWindow()
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
