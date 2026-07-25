from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QProcess, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .bpm import (
    GAPLESS_PREROLL_SECONDS,
    MAX_MIX_SECONDS,
    MID_MIX_SECONDS,
    MIN_MIX_DURATION_SECONDS,
    MIX_SECONDS,
    NO_TRANSITION_SECONDS,
    SHORT_LONG_MIX_SECONDS,
    SonoError,
    SonoTrack,
    SUPPORTED_AUDIO_EXTENSIONS,
    analyze_folder,
    analyze_track,
    display_title_from_path,
    find_tool,
    sort_tracks_by_bpm,
    smart_eq_filters,
    title_cycle_key_from_path,
)

APP_NAME = "SONO PLAY MINI"
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "sono_play_mini_logo.png"
TILE_SIZE = 170
CONTROL_GAP = 12
PANEL_WIDTH = TILE_SIZE * 2 + CONTROL_GAP + 24
PANEL_HEIGHT = 468
WINDOW_WIDTH = 430
WINDOW_HEIGHT = 512


class IndustrialPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")


class ClickableLogo(QLabel):
    clicked = Signal()
    dropped = Signal(object)

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._audio_paths_from_event(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        paths = self._audio_paths_from_event(event)
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def _audio_paths_from_event(self, event) -> list[Path]:  # noqa: ANN001
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths: list[Path] = []
        seen: set[Path] = set()
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path in seen:
                continue
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            paths.append(path)
            seen.add(path)
        return paths


class TransportButton(QPushButton):
    def __init__(self, mode: str, name: str) -> None:
        super().__init__("")
        self.mode = mode
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setFixedSize(TILE_SIZE, TILE_SIZE)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#c22922") if self.isEnabled() else QColor("#4c2b28")
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#2a100e"), 2))

        center_y = self.height() / 2
        if self.mode == "play":
            width = 100
            height = 116
            x_pos = (self.width() - width) / 2 + 4
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x_pos, center_y - height / 2),
                        QPointF(x_pos, center_y + height / 2),
                        QPointF(x_pos + width, center_y),
                    ]
                )
            )
            return

        width = 64
        height = 100
        gap = 6
        start_x = (self.width() - (width * 2 + gap)) / 2
        for offset in (0, width + gap):
            x_pos = start_x + offset
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x_pos, center_y - height / 2),
                        QPointF(x_pos, center_y + height / 2),
                        QPointF(x_pos + width, center_y),
                    ]
                )
            )


class AnalysisWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder

    def run(self) -> None:
        try:
            tracks, errors = analyze_folder(self.folder, progress=self.progress.emit)
        except SonoError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(tracks, errors)


class SonoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: AnalysisWorker | None = None
        self.folder_path: Path | None = None
        self.tracks: list[SonoTrack] = []
        self.play_index = 0
        self.played_cycle_titles: set[str] = set()
        self.current_player: QProcess | None = None
        self.players: list[QProcess] = []
        self.player_tool = "afplay"
        self.next_fade_in_seconds = MIX_SECONDS
        self.mix_timer = QTimer(self)
        self.mix_timer.setSingleShot(True)
        self.mix_timer.timeout.connect(self._auto_next_mix)
        self.stop_requested = False
        self.setWindowTitle(APP_NAME)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self._build_ui()
        self._apply_style()
        self._set_status("READY")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(10, 10, 10, 10)
        shell.setSpacing(0)

        self.panel = IndustrialPanel()
        self.panel.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)
        self.panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        shell.addWidget(self.panel, alignment=Qt.AlignCenter)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)

        self.logo = ClickableLogo("SONO\nPLAY\nMINI")
        self.logo.setObjectName("logo")
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setCursor(Qt.PointingHandCursor)
        self.logo.clicked.connect(self._choose_folder)
        self.logo.dropped.connect(self._drop_audio_paths)
        self.logo.setFixedSize(TILE_SIZE, TILE_SIZE)
        if LOGO_PATH.exists():
            pixmap = QPixmap(str(LOGO_PATH))
            self.logo.setPixmap(
                pixmap.scaled(TILE_SIZE, TILE_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(self.logo, alignment=Qt.AlignCenter)

        utility_controls = QHBoxLayout()
        utility_controls.setSpacing(CONTROL_GAP)
        self.play_button = self._transport_button("playButton", "play", "PLAY")
        self.next_button = self._transport_button("nextButton", "next", "NEXT")
        self.play_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.play_button.clicked.connect(self._start_playback)
        self.next_button.clicked.connect(self._next_track)
        utility_controls.addWidget(self.play_button, alignment=Qt.AlignCenter)
        utility_controls.addWidget(self.next_button, alignment=Qt.AlignCenter)
        layout.addLayout(utility_controls)

        self.current_title = QLabel("")
        self.current_title.setObjectName("currentTitle")
        self.current_title.setAlignment(Qt.AlignCenter)
        self.current_title.setWordWrap(True)
        self.current_title.setFont(self._led_font())
        layout.addWidget(self.current_title)

    def _led_font(self):  # -> QFont
        font = QFont("Courier New", 13, QFont.Bold)
        font.setStyleHint(QFont.Monospace)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        return font

    def _transport_button(self, object_name: str, mode: str, name: str) -> TransportButton:
        button = TransportButton(mode, name)
        button.setObjectName(object_name)
        return button

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            * { font-family: "Arial Narrow", "Arial", "Helvetica", sans-serif; }
            #root { background: #000000; }
            #panel {
                border: 0px;
                border-radius: 0px;
                background: #000000;
            }
            QLabel {
                color: #9d9688;
                font-size: 13px;
                font-weight: 800;
            }
            #logo {
                color: #d8d0c0;
                font-size: 56px;
                font-weight: 900;
                line-height: 0.9;
            }
            QPushButton {
                color: #e7dfcf;
                background: #11100f;
                border: 3px solid #2d2a25;
                border-radius: 0px;
                font-weight: 900;
            }
            #playButton {
                background: #151412;
                border-color: #3d3932;
            }
            #nextButton {
                background: #151412;
                border-color: #3d3932;
            }
            #playButton:hover:!disabled {
                border-color: #6d6155;
            }
            #playButton:pressed:!disabled {
                background: #201412;
                border-color: #85251f;
            }
            QPushButton:disabled {
                background: #0b0b0a;
                border-color: #24211d;
            }
            QPushButton:hover:!disabled {
                border-color: #6b6256;
            }
            QPushButton:pressed:!disabled {
                background: #9e2e27;
                color: #050505;
            }
            #currentTitle {
                min-height: 46px;
                max-height: 58px;
                padding: 6px 10px;
                color: #ffb000;
                background: #050505;
                border: 2px solid #2a2620;
                border-radius: 3px;
                font-family: "Courier New", monospace;
                font-size: 13px;
                font-weight: 900;
            }
            """
        )

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, APP_NAME)
        if folder:
            self.folder_path = Path(folder)
            self.tracks = []
            self.played_cycle_titles.clear()
            self.play_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.current_title.setText("SCANNING")
            self._start_analysis()

    def _set_status(self, text: str) -> None:
        status = (text or "READY").upper()
        self.setWindowTitle(APP_NAME if status == "READY" else f"{APP_NAME} - {status}")

    def _start_analysis(self) -> None:
        if not self.folder_path:
            self._set_status("NO FOLDER")
            return
        self._stop_playback()
        self.logo.setEnabled(False)
        self.play_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.current_title.setText("SCANNING")
        self._set_status("BPM 0%")

        self.thread = QThread()
        self.worker = AnalysisWorker(self.folder_path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._clear_worker)
        self.thread.start()

    def _on_progress(self, message: str, percent: int) -> None:
        self._set_status(f"{message} {percent}%")
        self.current_title.setText(f"SCANNING {percent}%")

    def _on_finished(self, tracks: list[SonoTrack], errors: list[str]) -> None:
        self.logo.setEnabled(True)
        self.tracks = tracks
        self.played_cycle_titles.clear()
        self.play_button.setEnabled(bool(self.tracks))
        self.next_button.setEnabled(False)
        self._set_status("READY")
        self.current_title.setToolTip("\n".join(errors[:12]) if errors else "")
        if self.tracks:
            self.current_title.setText("READY")
        else:
            self.current_title.setText("NO AUDIO")

    def _on_failed(self, message: str) -> None:
        self.logo.setEnabled(True)
        self._set_status("ERROR")
        self.current_title.setText(message.upper()[:80])

    def _clear_worker(self) -> None:
        self.worker = None
        self.thread = None

    def _track_title(self, track: SonoTrack) -> str:
        return display_title_from_path(track.path)

    def _track_display_text(self, track: SonoTrack) -> str:
        # The LED screen shows the track title only, on purpose: no BPM,
        # no key, no extra readout.
        return self._track_title(track)

    def _track_cycle_key(self, track: SonoTrack) -> str:
        return title_cycle_key_from_path(track.path)

    def _track_cycle_keys(self) -> set[str]:
        return {self._track_cycle_key(track) for track in self.tracks}

    def _mark_track_played(self, track: SonoTrack) -> None:
        self.played_cycle_titles.add(self._track_cycle_key(track))

    def _next_unplayed_index(self, *, update_cycle: bool) -> int:
        if not self.tracks:
            return 0
        if len(self.tracks) == 1:
            return 0

        current_index = min(self.play_index, len(self.tracks) - 1)
        current_key = self._track_cycle_key(self.tracks[current_index])
        played_titles = set(self.played_cycle_titles)
        all_titles = self._track_cycle_keys()

        if all_titles and all_titles.issubset(played_titles):
            played_titles = {current_key}
            if update_cycle:
                self.played_cycle_titles = set(played_titles)

        for offset in range(1, len(self.tracks) + 1):
            candidate_index = (current_index + offset) % len(self.tracks)
            candidate_key = self._track_cycle_key(self.tracks[candidate_index])
            if candidate_key not in played_titles:
                return candidate_index

        for offset in range(1, len(self.tracks) + 1):
            candidate_index = (current_index + offset) % len(self.tracks)
            if candidate_index != current_index:
                return candidate_index
        return current_index

    def _next_play_index(self) -> int:
        return self._next_unplayed_index(update_cycle=True)

    def _peek_next_play_index(self) -> int:
        return self._next_unplayed_index(update_cycle=False)

    def _drop_audio_paths(self, paths: list[Path]) -> None:
        audio_paths = self._valid_audio_paths(paths)
        if not audio_paths:
            self._set_status("DROP AUDIO")
            return

        tracks: list[SonoTrack] = []
        errors: list[str] = []
        for path in audio_paths:
            track, error = analyze_track(path)
            tracks.append(track)
            if error:
                errors.append(error)

        self._queue_dropped_tracks(tracks)
        tooltip = self.current_title.toolTip()
        if errors:
            tooltip = "\n".join(part for part in (tooltip, "\n".join(errors[:12])) if part)
        self.current_title.setToolTip(tooltip)

        if self.current_player:
            self._set_status("NEXT READY")
            self.current_title.setText(self._track_display_text(self.tracks[self.play_index]))
            self.next_button.setEnabled(self._has_next_track())
            return

        self._set_status("READY")
        self.current_title.setText(self._track_display_text(tracks[0]))

    def _drop_next_track(self, path: Path) -> None:
        self._drop_audio_paths([path])

    def _valid_audio_paths(self, paths: list[Path]) -> list[Path]:
        audio_paths: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved in seen:
                continue
            if resolved.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS or not resolved.is_file():
                continue
            audio_paths.append(resolved)
            seen.add(resolved)
        return audio_paths

    def _queue_dropped_tracks(self, dropped_tracks: list[SonoTrack]) -> None:
        if not dropped_tracks:
            return

        priority_track = dropped_tracks[0]
        additional_tracks = dropped_tracks[1:]
        if not self.tracks:
            self.tracks = [priority_track, *sort_tracks_by_bpm(additional_tracks)]
            self.play_index = 0
            self._sync_after_queue_change()
            return

        current_index = min(self.play_index, len(self.tracks) - 1)
        current_track = self.tracks[current_index]
        upcoming_tracks = self.tracks[current_index + 1 :] + self.tracks[:current_index]
        diluted_tracks = self._progressive_tracks_after(priority_track, [*upcoming_tracks, *additional_tracks])
        self.tracks = [current_track, priority_track, *diluted_tracks]
        self.play_index = 0
        self._sync_after_queue_change()

    def _queue_next_track(self, track: SonoTrack) -> None:
        self._queue_dropped_tracks([track])

    def _sync_after_queue_change(self) -> None:
        self.play_button.setEnabled(bool(self.tracks) and self.current_player is None)
        self.next_button.setEnabled(self.current_player is not None and self._has_next_track())

    def _progressive_tracks_after(self, anchor_track: SonoTrack, tracks: list[SonoTrack]) -> list[SonoTrack]:
        sorted_tracks = sort_tracks_by_bpm(tracks)
        if anchor_track.bpm is None:
            return sorted_tracks
        higher_or_equal = [
            track for track in sorted_tracks if track.bpm is not None and track.bpm >= anchor_track.bpm
        ]
        lower = [track for track in sorted_tracks if track.bpm is not None and track.bpm < anchor_track.bpm]
        unknown = [track for track in sorted_tracks if track.bpm is None]
        return [*higher_or_equal, *lower, *unknown]

    def _start_index_for_mode(self, mode: str) -> int:
        if not self.tracks:
            return 0
        if mode == "high":
            return min(len(self.tracks) - 1, max(0, (len(self.tracks) * 2) // 3))
        if mode == "half":
            return min(len(self.tracks) - 1, len(self.tracks) // 2)
        return 0

    def _start_playback(self, mode: str = "low") -> None:
        if not self.tracks:
            self._set_status("NO TRACKS")
            self.current_title.setText("NO TRACKS")
            return
        player_tool = self._playback_tool()
        if not player_tool:
            self._set_status("NO PLAYER")
            self.current_title.setText("INSTALL FFMPEG")
            return
        self.player_tool = player_tool
        self._stop_playback(reset_status=False)
        self.stop_requested = False
        self.played_cycle_titles.clear()
        self.play_index = self._start_index_for_mode(mode)
        self.play_button.setEnabled(False)
        self._play_current(fade_in=False)

    def _playback_tool(self) -> str | None:
        return find_tool("ffplay") or find_tool("afplay")

    def _play_current(self, fade_in: bool) -> None:
        if self.play_index >= len(self.tracks):
            self.play_index = 0

        track = self.tracks[self.play_index]
        self._mark_track_played(track)
        mix_seconds = self._transition_mix_seconds(track)
        fade_out = mix_seconds > 0
        self._sync_transport_buttons(playing=True)
        self._set_status(f"PLAY {self.play_index + 1}/{len(self.tracks)}")
        self.current_title.setText(self._track_display_text(track))

        # Only the immediately previous track is allowed to keep fading out
        # underneath the one we are about to start. Without this, a short
        # track whose own crossfade into the next one starts before the
        # earlier track's long outro fade has actually finished leaves two,
        # sometimes three, players running at once — audible as several
        # tracks and their vocals stepping on each other.
        self._retire_stale_players()

        player = QProcess(self)
        player.finished.connect(lambda *args, process=player: self._on_player_finished(process))
        player.errorOccurred.connect(lambda _error, process=player: self._on_player_error(process))
        self.players.append(player)
        self.current_player = player

        # The mix countdown must be armed from the moment this track's audio
        # actually starts, not from the moment we merely asked the OS to
        # launch it. Process fork/exec scheduling (especially while the
        # previous player is being torn down in _kill_players) is not
        # instantaneous and varies with system load, so starting the timer
        # right after calling start() lets that variable startup delay leak
        # straight into the crossfade point: the next track's fade-in would
        # fire before this track's audio has actually reached its outro,
        # which is what produces an occasional audible mix "décalage".
        # Arming the timer from QProcess.started instead removes that
        # dominant source of drift.
        fade_in_seconds_for_this_track = self.next_fade_in_seconds if fade_in else mix_seconds
        self.mix_timer.stop()
        if fade_out and track.duration_seconds:
            self.next_fade_in_seconds = mix_seconds
            delay_ms = max(1, int((track.duration_seconds - mix_seconds) * 1000))
            player.started.connect(
                lambda process=player, delay=delay_ms: self._arm_mix_timer(process, delay)
            )
        elif (
            track.duration_seconds
            and track.duration_seconds > GAPLESS_PREROLL_SECONDS
            and self._has_next_track()
        ):
            # No clean mix window here (short track, no mixable outro/intro,
            # or a vocal-heavy region), so we do not blend the two tracks.
            # We still start the next one a fraction of a second early so
            # the next player's own startup latency does not surface as a
            # beat of silence once this track reaches its natural end.
            self.next_fade_in_seconds = GAPLESS_PREROLL_SECONDS
            delay_ms = max(1, int((track.duration_seconds - GAPLESS_PREROLL_SECONDS) * 1000))
            player.started.connect(
                lambda process=player, delay=delay_ms: self._arm_mix_timer(process, delay)
            )
        else:
            self.next_fade_in_seconds = MIX_SECONDS

        player.start(
            self.player_tool,
            self._player_args(
                track,
                fade_in=fade_in,
                fade_out=fade_out,
                mix_seconds=fade_in_seconds_for_this_track,
            ),
        )

    def _arm_mix_timer(self, process: QProcess, delay_ms: int) -> None:
        if process is not self.current_player:
            return
        self.mix_timer.start(delay_ms)

    def _transition_mix_seconds(self, track: SonoTrack) -> float:
        next_index = self._peek_next_play_index()
        next_track = self.tracks[next_index]
        if next_track is track:
            return 0.0
        if not track.duration_seconds:
            return 0.0
        if track.duration_seconds < MIN_MIX_DURATION_SECONDS:
            return NO_TRANSITION_SECONDS
        if next_track.mixable_intro_seconds < MIX_SECONDS:
            return NO_TRANSITION_SECONDS

        outro_seconds = track.mixable_outro_seconds if track.mixable_outro_seconds >= MIX_SECONDS else MIX_SECONDS
        available_seconds = min(outro_seconds, next_track.mixable_intro_seconds, MAX_MIX_SECONDS)
        if available_seconds < MIX_SECONDS:
            return NO_TRANSITION_SECONDS

        if track.bpm is None or next_track.bpm is None:
            return MIX_SECONDS if available_seconds < SHORT_LONG_MIX_SECONDS else min(
                SHORT_LONG_MIX_SECONDS, available_seconds
            )

        bpm_gap = abs(track.bpm - next_track.bpm)
        if bpm_gap <= 3.0:
            return available_seconds
        if bpm_gap <= 6.0:
            return min(MID_MIX_SECONDS, available_seconds)
        if available_seconds >= SHORT_LONG_MIX_SECONDS:
            return SHORT_LONG_MIX_SECONDS
        return MIX_SECONDS

    def _player_args(
        self,
        track: SonoTrack,
        fade_in: bool,
        fade_out: bool,
        mix_seconds: float,
    ) -> list[str]:
        if Path(self.player_tool).name == "afplay":
            return [str(track.path)]

        args = ["-nodisp", "-autoexit", "-loglevel", "quiet"]
        filters = smart_eq_filters(track)
        if fade_in:
            filters.append(f"afade=t=in:st=0:d={mix_seconds:g}")
        if fade_out and track.duration_seconds:
            start = max(0.0, track.duration_seconds - mix_seconds)
            filters.append(f"afade=t=out:st={start:.3f}:d={mix_seconds:g}")
        if filters:
            args.extend(["-af", ",".join(filters)])
        args.append(str(track.path))
        return args

    def _on_player_error(self, process: QProcess) -> None:
        if process is self.current_player:
            self.current_title.setText("PLAYER ERROR")
            self.play_button.setEnabled(bool(self.tracks))
            self.next_button.setEnabled(False)

    def _has_next_track(self) -> bool:
        return len(self.tracks) > 1

    def _sync_transport_buttons(self, playing: bool) -> None:
        self.play_button.setEnabled(bool(self.tracks) and not playing)
        self.next_button.setEnabled(playing and self._has_next_track())

    def _auto_next_mix(self) -> None:
        if self.stop_requested or len(self.tracks) < 2:
            return
        self.play_index = self._next_play_index()
        self._play_current(fade_in=True)

    def _on_player_finished(self, process: QProcess) -> None:
        if process in self.players:
            self.players.remove(process)
        if self.stop_requested:
            return
        if process is not self.current_player:
            process.deleteLater()
            return
        process.deleteLater()
        self.mix_timer.stop()
        self.play_index = self._next_play_index() if self.tracks else 0
        self._play_current(fade_in=False)

    def _next_track(self) -> None:
        if not self.tracks:
            return
        if len(self.tracks) < 2:
            return
        next_index = self._next_play_index()

        self.mix_timer.stop()
        self.stop_requested = True
        self._kill_players()
        self.current_player = None
        self.stop_requested = False
        self.play_index = next_index
        self._play_current(fade_in=False)

    def _finish_playback(self) -> None:
        self.mix_timer.stop()
        self.current_player = None
        self._set_status("DONE")
        self.play_button.setEnabled(True)
        self.next_button.setEnabled(False)

    def _stop_playback(self, reset_status: bool = True) -> None:
        self.stop_requested = True
        self.mix_timer.stop()
        self._kill_players()
        self.current_player = None
        self.play_button.setEnabled(bool(self.tracks))
        self.next_button.setEnabled(False)
        if reset_status:
            self._set_status("READY")

    def _kill_players(self) -> None:
        for player in list(self.players):
            self._terminate_player(player)

    def _retire_stale_players(self) -> None:
        for player in list(self.players):
            if player is self.current_player:
                continue
            self._terminate_player(player)

    def _terminate_player(self, player: QProcess) -> None:
        try:
            player.finished.disconnect()
            player.errorOccurred.disconnect()
        except (RuntimeError, TypeError):
            pass
        if player.state() != QProcess.NotRunning:
            player.terminate()
            if not player.waitForFinished(250):
                player.kill()
                player.waitForFinished(1500)
        if player in self.players:
            self.players.remove(player)
        player.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._stop_playback(reset_status=False)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("RUSH OPERATOR")
    window = SonoWindow()
    window.show()
    return app.exec()
