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

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import sndz_play_mini.ui as ui  # noqa: E402


def _logo_path() -> Path:
    """Find the logo from source, PyInstaller temp data, or the macOS bundle."""
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        # .../SONO PLAY MINI.app/Contents/MacOS/SONO PLAY MINI
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(ui.APP_NAME)
    app.setOrganizationName("RUSH OPERATOR")

    logo_path = _logo_path()
    ui.LOGO_PATH = logo_path

    if logo_path.is_file():
        app.setWindowIcon(QIcon(str(logo_path)))

    window = ui.SonoWindow()
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
