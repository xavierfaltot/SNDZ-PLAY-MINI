from __future__ import annotations

import shutil
import subprocess
import warnings
from dataclasses import dataclass
from array import array
import os
import math
import re
from pathlib import Path
from typing import Callable

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

SONO_VERSION = "2.0"
SAMPLE_RATE = 11025
WINDOW_SAMPLES = 1024
HOP_SAMPLES = 512
ENERGY_FRAME_SECONDS = HOP_SAMPLES / SAMPLE_RATE
MIN_BPM = 60
MAX_BPM = 190
BPM_RANGE_MIN = 70
BPM_RANGE_MAX = 150
MAX_ANALYSIS_SECONDS = 120
INTRO_ANALYSIS_SECONDS = 32
OUTRO_ANALYSIS_SECONDS = 32
MIX_SECONDS = 8.0
# Mix windows are scanned in 4-second steps starting at MIX_SECONDS (see
# mixable_region_seconds_from_energies), so MAX_MIX_SECONDS must stay on
# that 8, 12, 16, ... grid or the scan will silently undershoot it.
MAX_MIX_SECONDS = 12.0
MID_MIX_SECONDS = 10.0
SHORT_LONG_MIX_SECONDS = 9.0
MIN_MIX_DURATION_SECONDS = 24.0
NO_TRANSITION_SECONDS = 0.0
# When no real mix window is offered (short track, no clean outro/intro,
# vocal-heavy region...), the player still starts the next track a fraction
# of a second early. This is not a mix: it only exists to absorb the OS-level
# process-spawn latency of launching the next ffplay/afplay process, so the
# switch does not read as a beat of silence between tracks.
GAPLESS_PREROLL_SECONDS = 0.35
EQ_LOW_CUT_HZ = 35
EQ_HIGH_CUT_HZ = 18000
# Rough vocal-presence gate for the crossfade window: a region is only
# offered up as "mixable" if it is not dominated by energy in the band
# where lead vocals sit. This does not detect vocals as such (that would
# need real source separation), it only measures how much of a segment's
# energy falls in the vocal formant range versus the full-band signal.
# A sustained high ratio there is a decent proxy for "someone is singing
# through most of this", which is exactly the region a crossfade should
# avoid so two vocal lines do not overlap.
VOCAL_BAND_HIGHPASS_HZ = 300
VOCAL_BAND_LOWPASS_HZ = 3400
VOCAL_BAND_FILTERS = [f"highpass=f={VOCAL_BAND_HIGHPASS_HZ}", f"lowpass=f={VOCAL_BAND_LOWPASS_HZ}"]
VOCAL_PRESENCE_RATIO_LIMIT = 0.52
LOUDNESS_TARGET_LUFS = -16
LOUDNESS_TRUE_PEAK_DB = -1.5
LOUDNESS_RANGE_LU = 9
FILENAME_BPM_PATTERN = re.compile(r"\[(\d{2,3}(?:[.,]\d+)?)\s*BPM\]", re.IGNORECASE)
TRAILING_DUPLICATE_PATTERN = re.compile(r"(?:[_\-\s]+(?:copy|copie))?(?:[_\-\s]+0?\d{1,3})$")
# Conservative markers for "same file, downloaded twice": a zero-padded
# auto-numbered suffix ("_02", "_03", ...) or a Finder/browser copy marker
# ("copy", "copie", "(1)", "(2)", ...). Deliberately narrower than
# TRAILING_DUPLICATE_PATTERN (which also strips real track numbers such as
# "Track 1") because this pattern feeds a hard exclusion, not a soft
# no-repeat hint: a false match here silently removes a track forever.
STRICT_DUPLICATE_SUFFIX_PATTERN = re.compile(r"(?:[_\-\s]+(?:copy|copie))?(?:[_\-\s]+0[0-9])$", re.IGNORECASE)
STRICT_DUPLICATE_PAREN_PATTERN = re.compile(r"\s*\(\d+\)$")
DUPLICATE_DURATION_TOLERANCE_SECONDS = 2.0
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".wav",
}
TOOL_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
    "/bin",
)


class SonoError(RuntimeError):
    pass


@dataclass(frozen=True)
class SonoTrack:
    path: Path
    bpm: float | None
    duration_seconds: float | None = None
    key: str = ""
    first_beat_seconds: float = 0.0
    variable_tempo: bool = False
    mixable_intro: bool = False
    mixable_intro_seconds: float = 0.0
    mixable_outro_seconds: float = 0.0


Estimator = Callable[[Path], float | None]
ProgressCallback = Callable[[str, int], None]


def find_tool(name: str) -> str | None:
    tool = shutil.which(name)
    if tool:
        return tool
    for folder in TOOL_DIRS:
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def require_tool(name: str) -> str:
    tool = find_tool(name)
    if not tool:
        raise SonoError(f"{name} not found")
    return tool


def find_audio_files(folder: Path) -> list[Path]:
    root = folder.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SonoError("Sound folder not found")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]
    return sorted(files, key=lambda path: str(path).lower())


def probe_duration_seconds(path: Path) -> float | None:
    ffprobe = require_tool("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def decode_audio_pcm(
    path: Path,
    max_seconds: int = MAX_ANALYSIS_SECONDS,
    start_seconds: float = 0.0,
    filters: list[str] | None = None,
) -> bytes:
    ffmpeg = require_tool("ffmpeg")
    command = [ffmpeg, "-nostdin", "-v", "error"]
    if start_seconds > 0:
        command.extend(["-ss", f"{start_seconds:.3f}"])
    command.extend(["-i", str(path), "-t", str(max_seconds), "-vn"])
    if filters:
        command.extend(["-af", ",".join(filters)])
    command.extend(["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"])
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        details = result.stderr.decode("utf-8", errors="ignore").strip()
        raise SonoError(details or f"Could not decode {path.name}")
    return result.stdout


def raw_rms_envelope(pcm: bytes) -> list[float]:
    window_bytes = WINDOW_SAMPLES * 2
    hop_bytes = HOP_SAMPLES * 2
    if len(pcm) < window_bytes * 8:
        return []

    values: list[float] = []
    for offset in range(0, len(pcm) - window_bytes, hop_bytes):
        values.append(float(audioop.rms(pcm[offset : offset + window_bytes], 2)))
    return values


def energy_envelope(pcm: bytes) -> list[float]:
    values = raw_rms_envelope(pcm)
    peak = max(values, default=0.0)
    if peak <= 0:
        return []
    return [value / peak for value in values]


def vocal_band_ratio_envelope(full_pcm: bytes, vocal_band_pcm: bytes) -> list[float]:
    """Fraction of each frame's raw energy that falls in the vocal band.

    Uses raw (non peak-normalized) RMS values on purpose: energy_envelope()
    normalizes each signal against its own peak, which would make a ratio
    between two independently-normalized series meaningless. A near-silent
    frame is reported as 0.0 rather than left to a noisy division.
    """
    full_raw = raw_rms_envelope(full_pcm)
    band_raw = raw_rms_envelope(vocal_band_pcm)
    length = min(len(full_raw), len(band_raw))
    ratios: list[float] = []
    for index in range(length):
        full_value = full_raw[index]
        if full_value <= 1.0:
            ratios.append(0.0)
            continue
        ratios.append(min(1.0, band_raw[index] / full_value))
    return ratios


def has_strong_vocal_presence(
    ratios: list[float], *, ratio_limit: float = VOCAL_PRESENCE_RATIO_LIMIT
) -> bool:
    active = [ratio for ratio in ratios if ratio > 0]
    if not active:
        return False
    return (sum(active) / len(active)) >= ratio_limit


def onset_envelope(energies: list[float]) -> list[float]:
    if len(energies) < 4:
        return []
    onsets = [0.0]
    previous = energies[0]
    for value in energies[1:]:
        change = value - previous
        onsets.append(change if change > 0 else 0.0)
        previous = value

    peak = max(onsets, default=0.0)
    if peak <= 0:
        return []
    return [value / peak for value in onsets]


def bpm_score(onsets: list[float], bpm: int) -> float:
    frames_per_second = SAMPLE_RATE / HOP_SAMPLES
    lag = round((60.0 / bpm) * frames_per_second)
    if lag <= 1 or len(onsets) <= lag * 3:
        return 0.0
    return sum(onsets[index] * onsets[index - lag] for index in range(lag, len(onsets)))


def estimate_bpm(path: Path, min_bpm: int = MIN_BPM, max_bpm: int = MAX_BPM) -> float | None:
    pcm = decode_audio_pcm(path)
    onsets = onset_envelope(energy_envelope(pcm))
    if not onsets or sum(onsets) < 0.2:
        return None

    scores = [(bpm_score(onsets, bpm), bpm) for bpm in range(min_bpm, max_bpm + 1)]
    best_score, best_bpm = max(scores, key=lambda item: item[0])
    if best_score <= 0:
        return None
    return normalize_bpm_to_range(float(best_bpm))


def normalize_bpm_to_range(
    bpm: float | None,
    min_bpm: int = BPM_RANGE_MIN,
    max_bpm: int = BPM_RANGE_MAX,
) -> float | None:
    if bpm is None or bpm <= 0:
        return None
    value = float(bpm)
    while value < min_bpm:
        value *= 2.0
    while value > max_bpm:
        value /= 2.0
    if value < min_bpm:
        return float(min_bpm)
    if value > max_bpm:
        return float(max_bpm)
    return round(value, 2)


def bpm_from_filename(path: Path) -> float | None:
    match = FILENAME_BPM_PATTERN.search(path.stem)
    if not match:
        return None
    try:
        bpm = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return normalize_bpm_to_range(bpm)


def title_cycle_key_from_path(path: Path) -> str:
    stem = FILENAME_BPM_PATTERN.sub("", path.stem)
    stem = re.sub(r"[_\-\s]+", "_", stem).strip("_ ")
    stem = TRAILING_DUPLICATE_PATTERN.sub("", stem).strip("_ ")
    return stem.casefold() or path.name.casefold()


def strict_duplicate_key_from_path(path: Path) -> str:
    stem = FILENAME_BPM_PATTERN.sub("", path.stem)
    stem = STRICT_DUPLICATE_PAREN_PATTERN.sub("", stem)
    stem = STRICT_DUPLICATE_SUFFIX_PATTERN.sub("", stem)
    stem = re.sub(r"[_\-\s]+", " ", stem).strip()
    return stem.casefold() or path.name.casefold()


def deduplicate_tracks(
    tracks: list[SonoTrack],
    *,
    duration_tolerance_seconds: float = DUPLICATE_DURATION_TOLERANCE_SECONDS,
) -> tuple[list[SonoTrack], list[tuple[SonoTrack, SonoTrack]]]:
    """Drop tracks that are the same sound saved twice under different names.

    Two tracks only count as duplicates when BOTH conditions hold: their
    filenames collapse to the same strict duplicate key (same title, only
    differing by an auto-numbered/copy suffix) AND their measured durations
    are within `duration_tolerance_seconds` of each other. Title alone is
    not enough, since two different songs can share a title fragment; this
    keeps the exclusion safe from false positives that would otherwise
    permanently hide a real, distinct track.

    Returns the surviving tracks (best quality per group, by file size) and
    the list of (kept, dropped) pairs for logging/reporting.
    """
    groups: dict[str, list[SonoTrack]] = {}
    for track in tracks:
        key = strict_duplicate_key_from_path(track.path)
        groups.setdefault(key, []).append(track)

    kept: list[SonoTrack] = []
    removed: list[tuple[SonoTrack, SonoTrack]] = []

    for candidates in groups.values():
        remaining = list(candidates)
        while remaining:
            anchor = remaining.pop(0)
            cluster = [anchor]
            still_remaining: list[SonoTrack] = []
            for other in remaining:
                if (
                    anchor.duration_seconds is not None
                    and other.duration_seconds is not None
                    and abs(anchor.duration_seconds - other.duration_seconds) <= duration_tolerance_seconds
                ):
                    cluster.append(other)
                else:
                    still_remaining.append(other)
            remaining = still_remaining

            if len(cluster) == 1:
                kept.append(cluster[0])
                continue

            def _quality(track: SonoTrack) -> int:
                try:
                    return track.path.stat().st_size
                except OSError:
                    return 0

            best = max(cluster, key=_quality)
            kept.append(best)
            removed.extend((best, track) for track in cluster if track is not best)

    return sort_tracks_by_bpm(kept), removed


def display_title_from_path(path: Path) -> str:
    stem = FILENAME_BPM_PATTERN.sub("", path.stem)
    stem = re.sub(r"[_\-\s]+", " ", stem).strip()
    stem = TRAILING_DUPLICATE_PATTERN.sub("", stem).strip()
    return stem.upper() or path.name.upper()


def is_mixable_intro_from_energies(energies: list[float]) -> bool:
    if len(energies) < 12:
        return False
    active = [value for value in energies if value > 0.08]
    active_ratio = len(active) / len(energies)
    mean_energy = sum(energies) / len(energies)
    peak_energy = max(energies, default=0.0)
    return active_ratio >= 0.35 and mean_energy >= 0.08 and peak_energy >= 0.22


def mixable_region_seconds_from_energies(
    energies: list[float],
    *,
    from_start: bool = True,
    vocal_ratios: list[float] | None = None,
) -> float:
    if not energies:
        return 0.0
    best = 0.0
    max_seconds = int(min(MAX_MIX_SECONDS, len(energies) * ENERGY_FRAME_SECONDS))
    for seconds in range(int(MIX_SECONDS), max_seconds + 1, 4):
        frame_count = max(12, int(seconds / ENERGY_FRAME_SECONDS))
        candidate = energies[:frame_count] if from_start else energies[-frame_count:]
        if not is_mixable_intro_from_energies(candidate):
            continue
        if vocal_ratios:
            candidate_ratios = vocal_ratios[:frame_count] if from_start else vocal_ratios[-frame_count:]
            if has_strong_vocal_presence(candidate_ratios):
                continue
        best = float(seconds)
    return best


def _vocal_band_ratios_for(path: Path, max_seconds: int, start_seconds: float, full_pcm: bytes) -> list[float] | None:
    # Best-effort: if the second ffmpeg decode (band-limited) fails for any
    # reason, fall back to the plain energy-only mixable check rather than
    # denying the crossfade outright.
    try:
        band_pcm = decode_audio_pcm(
            path, max_seconds=max_seconds, start_seconds=start_seconds, filters=VOCAL_BAND_FILTERS
        )
    except SonoError:
        return None
    return vocal_band_ratio_envelope(full_pcm, band_pcm)


def has_mixable_intro(path: Path) -> bool:
    try:
        pcm = decode_audio_pcm(path, max_seconds=INTRO_ANALYSIS_SECONDS)
    except SonoError:
        return False
    if not is_mixable_intro_from_energies(energy_envelope(pcm)):
        return False
    ratios = _vocal_band_ratios_for(path, INTRO_ANALYSIS_SECONDS, 0.0, pcm)
    return not (ratios and has_strong_vocal_presence(ratios))


def mixable_intro_seconds(path: Path) -> float:
    try:
        pcm = decode_audio_pcm(path, max_seconds=INTRO_ANALYSIS_SECONDS)
    except SonoError:
        return 0.0
    ratios = _vocal_band_ratios_for(path, INTRO_ANALYSIS_SECONDS, 0.0, pcm)
    return mixable_region_seconds_from_energies(energy_envelope(pcm), from_start=True, vocal_ratios=ratios)


def mixable_outro_seconds(path: Path, duration_seconds: float | None) -> float:
    if not duration_seconds or duration_seconds <= MIX_SECONDS:
        return 0.0
    start_seconds = max(0.0, duration_seconds - OUTRO_ANALYSIS_SECONDS)
    try:
        pcm = decode_audio_pcm(path, max_seconds=OUTRO_ANALYSIS_SECONDS, start_seconds=start_seconds)
    except SonoError:
        return 0.0
    ratios = _vocal_band_ratios_for(path, OUTRO_ANALYSIS_SECONDS, start_seconds, pcm)
    return mixable_region_seconds_from_energies(energy_envelope(pcm), from_start=False, vocal_ratios=ratios)


def first_beat_seconds_from_energies(energies: list[float]) -> float:
    if not energies:
        return 0.0
    threshold = max(0.18, min(0.55, (sum(energies) / len(energies)) * 2.0))
    for index, value in enumerate(energies):
        if value >= threshold:
            return round(index * ENERGY_FRAME_SECONDS, 3)
    return 0.0


def first_beat_seconds(path: Path) -> float:
    try:
        pcm = decode_audio_pcm(path, max_seconds=INTRO_ANALYSIS_SECONDS)
    except SonoError:
        return 0.0
    return first_beat_seconds_from_energies(energy_envelope(pcm))


def detect_variable_tempo(path: Path, bpm: float | None, duration_seconds: float | None) -> bool:
    if bpm is None or not duration_seconds or duration_seconds < 90:
        return False
    try:
        early = estimate_bpm_segment(path, start_seconds=0.0)
        late = estimate_bpm_segment(path, start_seconds=max(0.0, duration_seconds - MAX_ANALYSIS_SECONDS))
    except SonoError:
        return False
    if early is None or late is None:
        return False
    return abs(early - late) >= 4.0


def estimate_bpm_segment(path: Path, start_seconds: float) -> float | None:
    pcm = decode_audio_pcm(path, max_seconds=MAX_ANALYSIS_SECONDS, start_seconds=start_seconds)
    onsets = onset_envelope(energy_envelope(pcm))
    if not onsets or sum(onsets) < 0.2:
        return None
    scores = [(bpm_score(onsets, bpm), bpm) for bpm in range(MIN_BPM, MAX_BPM + 1)]
    best_score, best_bpm = max(scores, key=lambda item: item[0])
    return normalize_bpm_to_range(float(best_bpm)) if best_score > 0 else None


def _pcm_samples(pcm: bytes, max_samples: int = 8192) -> list[float]:
    samples = array("h")
    samples.frombytes(pcm[: max_samples * 2])
    if not samples:
        return []
    peak = max(abs(value) for value in samples) or 1
    return [value / peak for value in samples]


def _goertzel_power(samples: list[float], frequency: float) -> float:
    if not samples:
        return 0.0
    normalized = frequency / SAMPLE_RATE
    coefficient = 2.0 * math.cos(2.0 * math.pi * normalized)
    q1 = 0.0
    q2 = 0.0
    for sample in samples:
        q0 = coefficient * q1 - q2 + sample
        q2 = q1
        q1 = q0
    return q1 * q1 + q2 * q2 - coefficient * q1 * q2


def estimate_key(path: Path) -> str:
    try:
        pcm = decode_audio_pcm(path, max_seconds=24)
    except SonoError:
        return ""
    samples = _pcm_samples(pcm)
    if not samples:
        return ""

    chroma = [0.0] * 12
    for midi_note in range(36, 85):
        frequency = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
        chroma[midi_note % 12] += _goertzel_power(samples, frequency)
    peak = max(chroma, default=0.0)
    if peak <= 0:
        return ""
    chroma = [value / peak for value in chroma]

    best_score = -1.0
    best_key = ""
    for root in range(12):
        major_score = sum(chroma[(root + offset) % 12] * MAJOR_PROFILE[offset] for offset in range(12))
        minor_score = sum(chroma[(root + offset) % 12] * MINOR_PROFILE[offset] for offset in range(12))
        if major_score > best_score:
            best_score = major_score
            best_key = PITCH_CLASSES[root]
        if minor_score > best_score:
            best_score = minor_score
            best_key = f"{PITCH_CLASSES[root]}m"
    return best_key


def smart_eq_gains(track: SonoTrack) -> tuple[float, float]:
    if track.bpm is None:
        return 0.0, 0.0
    if track.bpm >= 132.0:
        return -1.5, 0.8
    if track.bpm <= 92.0:
        return 0.8, -0.4
    return 0.0, 0.0


def smart_eq_filters(track: SonoTrack) -> list[str]:
    bass_gain, presence_gain = smart_eq_gains(track)
    return [
        f"highpass=f={EQ_LOW_CUT_HZ}",
        f"lowpass=f={EQ_HIGH_CUT_HZ}",
        f"equalizer=f=100:t=q:w=1:g={bass_gain:g}",
        f"equalizer=f=2800:t=q:w=1:g={presence_gain:g}",
        "acompressor=threshold=-18dB:ratio=1.8:attack=15:release=250:makeup=1",
        (
            "loudnorm="
            f"I={LOUDNESS_TARGET_LUFS}:"
            f"TP={LOUDNESS_TRUE_PEAK_DB}:"
            f"LRA={LOUDNESS_RANGE_LU}"
        ),
    ]


def sort_tracks_by_bpm(tracks: list[SonoTrack]) -> list[SonoTrack]:
    return sorted(
        tracks,
        key=lambda track: (
            track.bpm is None,
            track.bpm if track.bpm is not None else 9999.0,
            track.path.name.lower(),
        ),
    )


def analyze_track(path: Path, estimator: Estimator = estimate_bpm) -> tuple[SonoTrack, str | None]:
    bpm = bpm_from_filename(path)
    try:
        if bpm is None:
            bpm = estimator(path)
        duration = probe_duration_seconds(path)
        key = estimate_key(path)
        first_beat = first_beat_seconds(path)
        variable_tempo = detect_variable_tempo(path, bpm, duration)
        intro_seconds = mixable_intro_seconds(path)
        outro_seconds = mixable_outro_seconds(path, duration)
        error = None
    except SonoError as exc:
        duration = None
        key = ""
        first_beat = 0.0
        variable_tempo = False
        intro_seconds = 0.0
        outro_seconds = 0.0
        error = f"{path.name}: {exc}"

    return (
        SonoTrack(
            path=path,
            bpm=bpm,
            duration_seconds=duration,
            key=key,
            first_beat_seconds=first_beat,
            variable_tempo=variable_tempo,
            mixable_intro=intro_seconds >= MIX_SECONDS,
            mixable_intro_seconds=intro_seconds,
            mixable_outro_seconds=outro_seconds,
        ),
        error,
    )


def analyze_folder(
    folder: Path,
    estimator: Estimator = estimate_bpm,
    progress: ProgressCallback | None = None,
) -> tuple[list[SonoTrack], list[str]]:
    files = find_audio_files(folder)
    if not files:
        raise SonoError("No supported sound file")

    tracks: list[SonoTrack] = []
    errors: list[str] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        if progress:
            progress(f"BPM {index}/{total}", int(((index - 1) / total) * 100))
        track, error = analyze_track(path, estimator=estimator)
        tracks.append(track)
        if error:
            errors.append(error)
        if progress:
            progress(f"BPM {index}/{total}", int((index / total) * 100))

    deduplicated, removed_pairs = deduplicate_tracks(tracks)
    for kept_track, dropped_track in removed_pairs:
        errors.append(
            f"{dropped_track.path.name}: duplicate of {kept_track.path.name}, skipped"
        )

    return deduplicated, errors
