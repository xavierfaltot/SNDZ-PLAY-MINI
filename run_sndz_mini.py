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
from sndz_play_mini.ui import APP_NAME, LOGO_PATH, SonoWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RUSH OPERATOR")
    if LOGO_PATH.exists():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))

    window = SonoWindow()
    # SONO PLAY MINI is an instrument, not a desktop utility window: launch
    # directly into the minimal black full-screen interface.
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
