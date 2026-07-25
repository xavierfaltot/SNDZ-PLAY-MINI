from __future__ import annotations

import struct
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget

from sndz_play_mini.bpm import (
    GAPLESS_PREROLL_SECONDS,
    MAX_MIX_SECONDS,
    SHORT_LONG_MIX_SECONDS,
    SonoTrack,
    analyze_folder,
    analyze_track,
    bpm_from_filename,
    deduplicate_tracks,
    display_title_from_path,
    energy_envelope,
    find_audio_files,
    find_tool,
    first_beat_seconds_from_energies,
    has_strong_vocal_presence,
    is_mixable_intro_from_energies,
    mixable_region_seconds_from_energies,
    NO_TRANSITION_SECONDS,
    normalize_bpm_to_range,
    smart_eq_filters,
    smart_eq_gains,
    sort_tracks_by_bpm,
    strict_duplicate_key_from_path,
    title_cycle_key_from_path,
    vocal_band_ratio_envelope,
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


def test_normalizes_bpm_to_dj_range() -> None:
    assert normalize_bpm_to_range(70.0) == 70.0
    assert normalize_bpm_to_range(62.0) == 124.0
    assert normalize_bpm_to_range(176.0) == 88.0


def test_uses_bpm_embedded_in_filename(tmp_path) -> None:
    track_path = tmp_path / "shazam_youtube_all_about_u_original_mix_02 [084 BPM].mp3"
    track_path.write_bytes(b"")

    track, error = analyze_track(
        track_path,
        estimator=lambda _path: (_ for _ in ()).throw(AssertionError("estimator should not run")),
    )

    assert error is None
    assert bpm_from_filename(track_path) == 84.0
    assert track.bpm == 84.0
    assert display_title_from_path(track_path) == "SHAZAM YOUTUBE ALL ABOUT U ORIGINAL MIX"
    assert title_cycle_key_from_path(track_path) == "shazam_youtube_all_about_u_original_mix"


def test_first_beat_uses_first_strong_energy_frame() -> None:
    energies = [0.01, 0.02, 0.03, 0.42, 0.45]

    assert first_beat_seconds_from_energies(energies) > 0.0


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


def test_analyze_track_uses_same_metadata_path(tmp_path) -> None:
    track_path = tmp_path / "single.mp3"
    track_path.write_bytes(b"")

    track, error = analyze_track(track_path, estimator=lambda _path: 121.0)

    assert error is None
    assert track.path == track_path
    assert track.bpm == 121.0


def test_mixable_intro_energy_gate() -> None:
    assert is_mixable_intro_from_energies([0.3] * 24)
    assert not is_mixable_intro_from_energies([0.0] * 24)
    assert not is_mixable_intro_from_energies([0.0] * 20 + [0.9])


def test_measures_long_mixable_regions() -> None:
    assert mixable_region_seconds_from_energies([0.3] * 700) == MAX_MIX_SECONDS
    assert mixable_region_seconds_from_energies([0.0] * 700) == 0.0


def _constant_pcm(amplitude: int, sample_count: int) -> bytes:
    return struct.pack(f"<{sample_count}h", *([amplitude] * sample_count))


def test_vocal_band_ratio_flags_midrange_heavy_signal() -> None:
    # ~18s of audio at SAMPLE_RATE so there is enough length to scan a full
    # mix window; a plain constant-amplitude PCM stands in for "no dynamics
    # here, just check the band split logic".
    sample_count = 200_000
    full_pcm = _constant_pcm(20000, sample_count)
    instrumental_band_pcm = _constant_pcm(4000, sample_count)  # little energy in vocal band
    vocal_band_pcm = _constant_pcm(18000, sample_count)  # most energy in vocal band

    instrumental_ratios = vocal_band_ratio_envelope(full_pcm, instrumental_band_pcm)
    vocal_ratios = vocal_band_ratio_envelope(full_pcm, vocal_band_pcm)

    assert not has_strong_vocal_presence(instrumental_ratios)
    assert has_strong_vocal_presence(vocal_ratios)


def test_vocal_presence_denies_the_crossfade_window() -> None:
    # Regression test for vocals overlapping between two tracks: a region
    # that would otherwise pass the plain energy gate must be rejected once
    # it is dominated by vocal-band energy, so the app falls back to a
    # clean cut instead of blending two vocal lines.
    sample_count = 200_000
    full_pcm = _constant_pcm(20000, sample_count)
    vocal_band_pcm = _constant_pcm(18000, sample_count)
    instrumental_band_pcm = _constant_pcm(4000, sample_count)

    energies = energy_envelope(full_pcm)
    vocal_ratios = vocal_band_ratio_envelope(full_pcm, vocal_band_pcm)
    instrumental_ratios = vocal_band_ratio_envelope(full_pcm, instrumental_band_pcm)

    assert mixable_region_seconds_from_energies(energies) == MAX_MIX_SECONDS
    assert mixable_region_seconds_from_energies(energies, vocal_ratios=instrumental_ratios) == MAX_MIX_SECONDS
    assert mixable_region_seconds_from_energies(energies, vocal_ratios=vocal_ratios) == 0.0


def test_smart_eq_gains_follow_energy_curve(tmp_path) -> None:
    assert smart_eq_gains(SonoTrack(tmp_path / "slow.mp3", 88.0)) == (0.8, -0.4)
    assert smart_eq_gains(SonoTrack(tmp_path / "fast.mp3", 138.0)) == (-1.5, 0.8)
    assert smart_eq_gains(SonoTrack(tmp_path / "mid.mp3", 118.0)) == (0.0, 0.0)


def test_smart_eq_filters_are_playback_only(tmp_path) -> None:
    filters = smart_eq_filters(SonoTrack(tmp_path / "fast.mp3", 138.0))

    assert "highpass=f=35" in filters
    assert "lowpass=f=18000" in filters
    assert "equalizer=f=100:t=q:w=1:g=-1.5" in filters
    assert any(filter_spec.startswith("acompressor=") for filter_spec in filters)
    assert "loudnorm=I=-16:TP=-1.5:LRA=9" in filters


def test_tool_lookup_returns_none_for_missing_tool() -> None:
    assert find_tool("sndz_missing_tool_for_test") is None


def test_deduplicate_drops_same_title_and_close_duration(tmp_path) -> None:
    original = SonoTrack(tmp_path / "shazam_youtube_track_a.mp3", 120.0, duration_seconds=200.0)
    auto_numbered_copy = SonoTrack(tmp_path / "shazam_youtube_track_a_02.mp3", 120.0, duration_seconds=200.4)

    kept, removed = deduplicate_tracks([original, auto_numbered_copy])

    assert [track.path.name for track in kept] == ["shazam_youtube_track_a.mp3"]
    assert len(removed) == 1


def test_deduplicate_keeps_larger_file_between_true_duplicates(tmp_path) -> None:
    small = tmp_path / "song.mp3"
    small.write_bytes(b"x" * 500)
    large = tmp_path / "song(1).mp3"
    large.write_bytes(b"x" * 1000)

    kept, removed = deduplicate_tracks(
        [
            SonoTrack(small, 100.0, duration_seconds=150.0),
            SonoTrack(large, 100.0, duration_seconds=150.1),
        ]
    )

    assert [track.path.name for track in kept] == ["song(1).mp3"]
    assert len(removed) == 1


def test_deduplicate_does_not_merge_same_title_with_different_duration(tmp_path) -> None:
    # A trailing "_01"/"_02" is only treated as an auto-generated duplicate
    # marker if the durations also match; otherwise two distinct tracks
    # that happen to share a title fragment must never be silently dropped.
    first = SonoTrack(tmp_path / "dj_steef_edits_vol_7_track_01.mp3", 120.0, duration_seconds=90.0)
    second = SonoTrack(tmp_path / "dj_steef_edits_vol_7_track_02.mp3", 120.0, duration_seconds=400.0)

    kept, removed = deduplicate_tracks([first, second])

    assert {track.path.name for track in kept} == {
        "dj_steef_edits_vol_7_track_01.mp3",
        "dj_steef_edits_vol_7_track_02.mp3",
    }
    assert removed == []


def test_deduplicate_does_not_touch_real_track_numbers(tmp_path) -> None:
    # "Track 1" / "Track 2" (single digit, not zero-padded) are real title
    # numbers, not auto-dedup markers, and must stay distinct even with
    # unknown duration.
    first = SonoTrack(tmp_path / "dj_steef_edits_vol_7_track_1.mp3", 120.0, duration_seconds=None)
    second = SonoTrack(tmp_path / "dj_steef_edits_vol_7_track_2.mp3", 122.0, duration_seconds=None)

    kept, removed = deduplicate_tracks([first, second])

    assert len(kept) == 2
    assert removed == []


def test_strict_duplicate_key_ignores_auto_numbered_and_paren_suffixes(tmp_path) -> None:
    base_key = strict_duplicate_key_from_path(tmp_path / "shazam_youtube_track_a.mp3")

    assert strict_duplicate_key_from_path(tmp_path / "shazam_youtube_track_a_02.mp3") == base_key
    assert strict_duplicate_key_from_path(tmp_path / "shazam_youtube_track_a(1).mp3") == base_key
    assert strict_duplicate_key_from_path(tmp_path / "shazam_youtube_track_a_1.mp3") != base_key


def test_analyze_folder_excludes_duplicate_and_reports_it(tmp_path) -> None:
    (tmp_path / "track_a.mp3").write_bytes(b"")
    (tmp_path / "track_a_02.mp3").write_bytes(b"")

    def fake_estimator(path):
        return 120.0

    def fake_probe(path):
        return 200.0

    import sndz_play_mini.bpm as bpm_module

    original_probe = bpm_module.probe_duration_seconds
    bpm_module.probe_duration_seconds = fake_probe
    try:
        tracks, errors = analyze_folder(tmp_path, estimator=fake_estimator)
    finally:
        bpm_module.probe_duration_seconds = original_probe

    assert len(tracks) == 1
    assert any("duplicate of" in error for error in errors)


def test_ui_is_logo_driven_and_minimal(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "SONO PLAY MINI"
    assert window.play_button.text() == ""
    assert window.next_button.text() == ""
    assert window.play_button.accessibleName() == "PLAY"
    assert window.next_button.accessibleName() == "NEXT"
    assert not hasattr(window, "stop_button")
    assert not hasattr(window, "low_button")
    assert not hasattr(window, "half_button")
    assert not hasattr(window, "high_button")
    assert window.play_button.width() == window.logo.width()
    assert window.next_button.width() == window.logo.width()
    assert window.play_button.height() == window.logo.height()
    assert window.next_button.height() == window.logo.height()
    assert window.play_button.y() == window.next_button.y()
    assert window.play_button.x() < window.next_button.x()
    assert window.panel.width() == PANEL_WIDTH
    assert window.panel.height() == PANEL_HEIGHT
    assert 46 <= window.current_title.height() <= 58
    assert window.maximumWidth() > window.minimumWidth()
    assert window.findChildren(QLineEdit) == []
    assert window.findChildren(QListWidget) == []

    window.close()
    assert app is not None


def test_led_screen_shows_title_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    track = SonoTrack(tmp_path / "acid_mondays_universal_rhythm.mp3", 128.0, key="Am")

    text = window._track_display_text(track)

    assert text == "ACID MONDAYS UNIVERSAL RHYTHM"
    assert "BPM" not in text
    assert "KEY" not in text

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
    assert window.windowTitle() == "SONO PLAY MINI - BPM 42%"
    window._set_status("READY")
    assert window.windowTitle() == "SONO PLAY MINI"

    window.close()
    assert app is not None


def test_start_buttons_pick_bpm_zones(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "slow.mp3", 80.0),
        SonoTrack(tmp_path / "mid_a.mp3", 100.0),
        SonoTrack(tmp_path / "mid_b.mp3", 120.0),
        SonoTrack(tmp_path / "fast.mp3", 140.0),
    ]

    assert window._start_index_for_mode("low") == 0
    assert window._start_index_for_mode("half") == 2
    assert window._start_index_for_mode("high") == 2

    window.close()
    assert app is not None


def test_playback_prefers_ffplay_for_eq(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()

    monkeypatch.setattr(
        "sndz_play_mini.ui.find_tool",
        lambda name: f"/usr/bin/{name}" if name in {"ffplay", "afplay"} else None,
    )

    assert window._playback_tool() == "/usr/bin/ffplay"

    window.close()
    assert app is not None


def test_ffplay_args_include_smart_eq_and_fades(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.player_tool = "ffplay"
    track = SonoTrack(tmp_path / "fast.mp3", 138.0, duration_seconds=180.0)

    args = window._player_args(track, fade_in=True, fade_out=True, mix_seconds=8.0)
    filters = args[args.index("-af") + 1]

    assert "highpass=f=35" in filters
    assert "lowpass=f=18000" in filters
    assert "equalizer=f=100:t=q:w=1:g=-1.5" in filters
    assert "loudnorm=I=-16:TP=-1.5:LRA=9" in filters
    assert "afade=t=in:st=0:d=8" in filters
    assert "afade=t=out:st=172.000:d=8" in filters

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
    assert window.next_button.isEnabled()

    window.close()
    assert app is not None


def test_last_track_loops_to_calmest_without_stop(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "slow.mp3", 80.0),
        SonoTrack(tmp_path / "fast.mp3", 140.0),
    ]
    played_indexes: list[int] = []

    monkeypatch.setattr(window, "_play_current", lambda fade_in: played_indexes.append(window.play_index))

    window.play_index = 1
    window._auto_next_mix()

    assert window.play_index == 0
    assert played_indexes == [0]

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


def test_dropped_track_is_queued_after_current_track(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "one.mp3", 90.0),
        SonoTrack(tmp_path / "two.mp3", 100.0),
    ]
    dropped = SonoTrack(tmp_path / "drop.mp3", 95.0)

    window.play_index = 0
    window._queue_next_track(dropped)

    assert [track.path.name for track in window.tracks] == ["one.mp3", "drop.mp3", "two.mp3"]

    window.close()
    assert app is not None


def test_dropped_track_after_last_track_becomes_next_in_loop(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "slow.mp3", 80.0),
        SonoTrack(tmp_path / "fast.mp3", 140.0),
    ]
    dropped = SonoTrack(tmp_path / "drop.mp3", 132.0)

    window.play_index = 1
    window._queue_next_track(dropped)

    assert [track.path.name for track in window.tracks] == ["fast.mp3", "drop.mp3", "slow.mp3"]
    assert (window.play_index + 1) % len(window.tracks) == 1

    window.close()
    assert app is not None


def test_multiple_dropped_tracks_keep_first_next_and_dilute_rest_by_bpm(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "slow.mp3", 80.0),
        SonoTrack(tmp_path / "current.mp3", 100.0),
        SonoTrack(tmp_path / "fast.mp3", 140.0),
    ]
    dropped_tracks = [
        SonoTrack(tmp_path / "priority.mp3", 126.0),
        SonoTrack(tmp_path / "warm.mp3", 92.0),
        SonoTrack(tmp_path / "peak.mp3", 132.0),
    ]

    window.play_index = 1
    window._queue_dropped_tracks(dropped_tracks)

    assert [track.path.name for track in window.tracks] == [
        "current.mp3",
        "priority.mp3",
        "peak.mp3",
        "fast.mp3",
        "slow.mp3",
        "warm.mp3",
    ]
    assert window.play_index == 0

    window.close()
    assert app is not None


def test_multiple_drop_paths_are_analyzed_in_drop_order(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [SonoTrack(tmp_path / "current.mp3", 100.0)]
    paths = [tmp_path / "first.mp3", tmp_path / "second.mp3", tmp_path / "third.mp3"]
    for path in paths:
        path.write_bytes(b"")

    bpms = {"first.mp3": 128.0, "second.mp3": 90.0, "third.mp3": 130.0}
    monkeypatch.setattr(
        "sndz_play_mini.ui.analyze_track",
        lambda path: (SonoTrack(path, bpms[path.name]), None),
    )

    window._drop_audio_paths(paths)

    assert [track.path.name for track in window.tracks] == [
        "current.mp3",
        "first.mp3",
        "second.mp3",
        "third.mp3",
    ]

    window.close()
    assert app is not None


def test_drop_next_track_keeps_current_title_while_playing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [SonoTrack(tmp_path / "current.mp3", 100.0)]
    dropped_path = tmp_path / "priority.mp3"
    dropped_path.write_bytes(b"")
    dropped = SonoTrack(dropped_path, 110.0)

    class FakePlayer:
        pass

    window.current_player = FakePlayer()  # type: ignore[assignment]
    window.current_title.setText("CURRENT")
    monkeypatch.setattr("sndz_play_mini.ui.analyze_track", lambda _path: (dropped, None))

    window._drop_next_track(dropped_path)

    assert [track.path.name for track in window.tracks] == ["current.mp3", "priority.mp3"]
    assert window.current_title.text() == "CURRENT"
    assert window.next_button.isEnabled()

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

    assert window._transition_mix_seconds(window.tracks[0]) == MAX_MIX_SECONDS

    window.tracks[1] = SonoTrack(
        tmp_path / "two.mp3",
        138.0,
        duration_seconds=240.0,
        mixable_intro=True,
        mixable_intro_seconds=28.0,
        mixable_outro_seconds=28.0,
    )
    assert window._transition_mix_seconds(window.tracks[0]) == SHORT_LONG_MIX_SECONDS

    window.tracks[1] = SonoTrack(
        tmp_path / "two.mp3",
        122.0,
        duration_seconds=240.0,
        mixable_intro=True,
        mixable_intro_seconds=4.0,
        mixable_outro_seconds=28.0,
    )
    assert window._transition_mix_seconds(window.tracks[0]) == NO_TRANSITION_SECONDS

    window.close()
    assert app is not None


def test_transition_is_zero_when_long_mix_is_not_possible(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "one.mp3", 120.0, duration_seconds=180.0),
        SonoTrack(tmp_path / "two.mp3", 122.0, duration_seconds=180.0, mixable_intro_seconds=0.0),
    ]

    assert window._transition_mix_seconds(window.tracks[0]) == NO_TRANSITION_SECONDS

    window.close()
    assert app is not None


def test_mix_timer_waits_for_process_start_before_arming(monkeypatch, tmp_path) -> None:
    # Regression test for the crossfade "décalage": the mix countdown must
    # not start ticking the instant we call player.start(). It has to wait
    # for the OS to actually confirm the process is running, otherwise
    # process-launch jitter shifts the whole crossfade earlier than the
    # track's real audio position.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.player_tool = "true"  # trivial process guaranteed to exist and to emit `started`
    window.tracks = [
        SonoTrack(
            tmp_path / "one.mp3",
            120.0,
            duration_seconds=200.0,
            mixable_intro_seconds=8.0,
            mixable_outro_seconds=8.0,
        ),
        SonoTrack(
            tmp_path / "two.mp3",
            121.0,
            duration_seconds=200.0,
            mixable_intro=True,
            mixable_intro_seconds=8.0,
            mixable_outro_seconds=8.0,
        ),
    ]
    window.play_index = 0

    window._play_current(fade_in=False)

    assert not window.mix_timer.isActive()

    for _ in range(50):
        app.processEvents()
        if window.mix_timer.isActive():
            break

    assert window.mix_timer.isActive()

    window.close()
    assert app is not None


def test_gapless_preroll_still_arms_timer_without_a_real_mix(monkeypatch, tmp_path) -> None:
    # Regression test for the silent gap between tracks: when no clean mix
    # window is offered (here, the track is shorter than
    # MIN_MIX_DURATION_SECONDS), the player must not simply wait for the
    # process to exit before launching the next one. It should still arm
    # the mix timer, using GAPLESS_PREROLL_SECONDS rather than a real mix
    # duration, so the next track's own startup latency does not surface as
    # a beat of silence.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.player_tool = "true"  # trivial process guaranteed to exist and to emit `started`
    window.tracks = [
        SonoTrack(
            tmp_path / "short_one.mp3",
            120.0,
            duration_seconds=15.0,  # below MIN_MIX_DURATION_SECONDS: no real mix window
            mixable_intro_seconds=8.0,
            mixable_outro_seconds=8.0,
        ),
        SonoTrack(
            tmp_path / "two.mp3",
            121.0,
            duration_seconds=200.0,
            mixable_intro=True,
            mixable_intro_seconds=8.0,
            mixable_outro_seconds=8.0,
        ),
    ]
    window.play_index = 0

    assert window._transition_mix_seconds(window.tracks[0]) == NO_TRANSITION_SECONDS

    window._play_current(fade_in=False)

    assert window.next_fade_in_seconds == GAPLESS_PREROLL_SECONDS

    for _ in range(50):
        app.processEvents()
        if window.mix_timer.isActive():
            break

    assert window.mix_timer.isActive()

    window.close()
    assert app is not None


def test_retire_stale_players_keeps_only_current(monkeypatch) -> None:
    # Regression test for three tracks (and their vocals) playing at once:
    # starting a new track must forcibly cut anything older than the
    # immediately previous one, never letting a third player linger.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()

    stale_one = QProcess(window)
    stale_two = QProcess(window)
    current = QProcess(window)
    window.players = [stale_one, stale_two, current]
    window.current_player = current

    window._retire_stale_players()

    assert window.players == [current]

    window.close()
    assert app is not None


def test_play_current_retires_players_older_than_the_previous_track(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.player_tool = "true"
    window.tracks = [
        SonoTrack(tmp_path / "one.mp3", 120.0, duration_seconds=200.0),
        SonoTrack(tmp_path / "two.mp3", 121.0, duration_seconds=200.0),
    ]

    ghost = QProcess(window)
    window.players = [ghost]
    window.current_player = None
    window.play_index = 0

    window._play_current(fade_in=False)

    assert ghost not in window.players
    assert window.players == [window.current_player]

    window.close()
    assert app is not None


def test_title_cycle_skips_repeated_titles_until_all_others_play(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    window = SonoWindow()
    window.tracks = [
        SonoTrack(tmp_path / "same_title [084 BPM].mp3", 84.0),
        SonoTrack(tmp_path / "same_title_02 [084 BPM].mp3", 84.0),
        SonoTrack(tmp_path / "other_title [090 BPM].mp3", 90.0),
    ]

    window.play_index = 0
    window.played_cycle_titles = {window._track_cycle_key(window.tracks[0])}

    assert window._next_play_index() == 2

    window.play_index = 2
    window.played_cycle_titles.add(window._track_cycle_key(window.tracks[2]))
    assert window._next_play_index() in {0, 1}
    assert window._next_play_index() != 2

    window.close()
    assert app is not None
