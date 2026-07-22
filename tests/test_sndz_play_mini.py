from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget

from sndz_play_mini.bpm import (
    SonoTrack,
    analyze_folder,
    find_audio_files,
    find_tool,
    is_mixable_intro_from_energies,
    mixable_region_seconds_from_energies,
    sort_tracks_by_bpm,
)
from sndz_play_mini.ui import PANEL_HEIGHT, PANEL_WIDTH, SonoWindow


def test_finds_supported_audio_recursively(tmp_path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.wav").write_bytes(b"")
    (nested / "skip.txt").write_text("no", encoding="utf-8")

    assert [path.name for path in find_audio_files(tmp_path)] == ["a.mp3", "b.wav"]


def test_sorts_from_low_bpm_to_high_bpm(tmp_path) -> None:
    slow = SonoTrack(tmp_path / "slow.mp3", 82.0)
    fast = SonoTrack(tmp_path / "fast.mp3", 132.0)
    unknown = SonoTrack(tmp_path / "unknown.mp3", None)
    mid = SonoTrack(tmp_path / "mid.mp3", 108.0)

    assert sort_tracks_by_bpm([unknown, fast, slow, mid]) == [slow, mid, fast, unknown]


def test_analyze_folder_uses_estimator_and_sorts(tmp_path) -> None:
    for name in ("c.mp3", "a.mp3", "b.mp3"):
        (tmp_path / name).write_bytes(b"")
    bpms = {"a.mp3": 128.0, "b.mp3": 90.0, "c.mp3": 110.0}

    tracks, errors = analyze_folder(tmp_path, estimator=lambda path: bpms[path.name])

    assert errors == []
    assert [(track.path.name, track.bpm) for track in tracks] == [
        ("b.mp3", 90.0),
        ("c.mp3", 110.0),
        ("a.mp3", 128.0),
    ]


def test_mixable_intro_energy_gate() -> None:
    assert is_mixable_intro_from_energies([0.3] * 24)
    assert not is_mixable_intro_from_energies([0.0] * 24)
    assert not is_mixable_intro_from_energies([0.0] * 20 + [0.9])


def test_measures_long_mixable_regions() -> None:
    assert mixable_region_seconds_from_energies([0.3] * 700) >= 28.0
    assert mixable_region_seconds_from_energies([0.0] * 700) == 0.0


def test_tool_lookup_returns_none_for_missing_tool() -> None:
    assert find_tool("sndz_missing_tool_for_test") is None


def test_ui_is_logo_driven_and_minimal(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "SNDZ PLAY MINI"
    assert window.play_button.text() == ""
    assert window.next_button.text() == ""
    assert window.play_button.accessibleName() == "PLAY"
    assert window.next_button.accessibleName() == "NEXT"
    assert not hasattr(window, "stop_button")
    assert window.play_button.width() == window.logo.width()
    assert window.next_button.width() == window.logo.width()
    assert window.play_button.height() == window.logo.height()
    assert window.next_button.height() == window.logo.height()
    assert window.play_button.y() == window.next_button.y()
    assert window.play_button.x() < window.next_button.x()
    assert window.panel.width() == PANEL_WIDTH
    assert window.panel.height() == PANEL_HEIGHT
    assert window.maximumWidth() > window.minimumWidth()
    assert window.findChildren(QLineEdit) == []
    assert window.findChildren(QListWidget) == []

    window.close()
    assert app is not None


def test_maximized_layout_keeps_mini_panel_centered(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.show()
    window.resize(1000, 800)
    app.processEvents()

    root_rect = window.centralWidget().rect()
    panel_rect = window.panel.geometry()

    assert window.panel.width() == PANEL_WIDTH
    assert window.panel.height() == PANEL_HEIGHT
    assert abs(panel_rect.center().x() - root_rect.center().x()) <= 1
    assert abs(panel_rect.center().y() - root_rect.center().y()) <= 1

    window.close()
    assert app is not None


def test_status_progress_uses_title_bar(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()

    window._set_status("BPM 42%")
    assert window.windowTitle() == "SNDZ PLAY MINI - BPM 42%"
    window._set_status("READY")
    assert window.windowTitle() == "SNDZ PLAY MINI"

    window.close()
    assert app is not None


def test_next_stays_enabled_until_last_track(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "one.mp3", 90.0),
        SonoTrack(tmp_path / "two.mp3", 100.0),
        SonoTrack(tmp_path / "three.mp3", 110.0),
    ]

    window.play_index = 0
    window._sync_transport_buttons(playing=True)
    assert window.next_button.isEnabled()

    window.play_index = 1
    window._sync_transport_buttons(playing=True)
    assert window.next_button.isEnabled()

    window.play_index = 2
    window._sync_transport_buttons(playing=True)
    assert not window.next_button.isEnabled()

    window.close()
    assert app is not None


def test_next_can_advance_multiple_times(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "one.mp3", 90.0),
        SonoTrack(tmp_path / "two.mp3", 100.0),
        SonoTrack(tmp_path / "three.mp3", 110.0),
    ]
    played_indexes: list[int] = []

    monkeypatch.setattr(window, "_kill_players", lambda: None)
    monkeypatch.setattr(window, "_play_current", lambda fade_in: played_indexes.append(window.play_index))

    window.play_index = 0
    window._next_track()
    window._next_track()

    assert played_indexes == [1, 2]
    assert window.play_index == 2

    window.close()
    assert app is not None


def test_uses_long_mix_for_similar_bpm_and_long_regions(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(
            tmp_path / "one.mp3",
            120.0,
            duration_seconds=240.0,
            mixable_intro_seconds=8.0,
            mixable_outro_seconds=28.0,
        ),
        SonoTrack(
            tmp_path / "two.mp3",
            122.0,
            duration_seconds=240.0,
            mixable_intro=True,
            mixable_intro_seconds=28.0,
            mixable_outro_seconds=28.0,
        ),
    ]

    assert window._transition_mix_seconds(window.tracks[0]) == 28.0

    window.tracks[1] = SonoTrack(
        tmp_path / "two.mp3",
        138.0,
        duration_seconds=240.0,
        mixable_intro=True,
        mixable_intro_seconds=28.0,
        mixable_outro_seconds=28.0,
    )
    assert window._transition_mix_seconds(window.tracks[0]) == 16.0

    window.tracks[1] = SonoTrack(
        tmp_path / "two.mp3",
        122.0,
        duration_seconds=240.0,
        mixable_intro=True,
        mixable_intro_seconds=4.0,
        mixable_outro_seconds=28.0,
    )
    assert window._transition_mix_seconds(window.tracks[0]) == 0.0

    window.close()
    assert app is not None
