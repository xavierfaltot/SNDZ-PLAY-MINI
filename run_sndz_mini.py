#!/usr/bin/env python3
"""Launch SONO PLAY MINI from the source checkout."""

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

from sndz_play_mini.ui import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
