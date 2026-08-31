#!/usr/bin/env python3
"""Launch SONO PLAY MINI from the source checkout or frozen macOS app."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Install the distributed whole-track BPM analyser before the UI imports
# the bpm helpers. This keeps the existing player/mix code intact while
# making every folder analysis use the validated global tempo.
from sndz_play_mini.global_bpm import install as install_global_bpm  # noqa: E402

install_global_bpm()

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import sndz_play_mini.ui as ui  # noqa: E402


def _logo_path() -> Path:
    """Return the SONO logo path both from source and from PyInstaller."""
    candidates: list[Path] = []

    # PyInstaller extracts collected package data under sys._MEIPASS.
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

    # Normal source checkout.
    candidates.extend(
        [
            ROOT / "src" / "sndz_play_mini" / "assets" / "sono_play_mini_logo.png",
            Path(ui.__file__).resolve().parent / "assets" / "sono_play_mini_logo.png",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Keep a deterministic path so the UI can fall back cleanly if an asset
    # is genuinely missing.
    return candidates[0]


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(ui.APP_NAME)
    app.setOrganizationName("RUSH OPERATOR")

    # Use the real packaged image instead of the SONO/PLAY/MINI text fallback.
    logo_path = _logo_path()
    ui.LOGO_PATH = logo_path

    # Full screen stays black, but the instrument itself remains MINI and
    # centered instead of scaling visually to fill the display.
    ui.TILE_SIZE = 145
    ui.CONTROL_GAP = 8
    ui.PANEL_WIDTH = ui.TILE_SIZE * 2 + ui.CONTROL_GAP + 18
    ui.PANEL_HEIGHT = 390
    ui.WINDOW_WIDTH = 340
    ui.WINDOW_HEIGHT = 430

    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    window = ui.SonoWindow()
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
