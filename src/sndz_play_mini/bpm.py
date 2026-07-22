from __future__ import annotations

import shutil
import subprocess
import warnings
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

SONO_VERSION = "1.0"
SAMPLE_RATE = 11025
WINDOW_SAMPLES = 1024
HOP_SAMPLES = 512
ENERGY_FRAME_SECONDS = HOP_SAMPLES / SAMPLE_RATE
MIN_BPM = 60
MAX_BPM = 190
MAX_ANALYSIS_SECONDS = 120
INTRO_ANALYSIS_SECONDS = 32
OUTRO_ANALYSIS_SECONDS = 32
MIX_SECONDS = 8.0
MAX_MIX_SECONDS = 28.0
MIN_MIX_DURATION_SECONDS = 24.0
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
) -> bytes:
    ffmpeg = require_tool("ffmpeg")
    command = [ffmpeg, "-nostdin", "-v", "error"]
    if start_seconds > 0:
        command.extend(["-ss", f"{start_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(path),
            "-t",
            str(max_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        details = result.stderr.decode("utf-8", errors="ignore").strip()
        raise SonoError(details or f"Could not decode {path.name}")
    return result.stdout


def energy_envelope(pcm: bytes) -> list[float]:
    window_bytes = WINDOW_SAMPLES * 2
    hop_bytes = HOP_SAMPLES * 2
    if len(pcm) < window_bytes * 8:
        return []

    values: list[float] = []
    for offset in range(0, len(pcm) - window_bytes, hop_bytes):
        values.append(float(audioop.rms(pcm[offset : offset + window_bytes], 2)))

    peak = max(values, default=0.0)
    if peak <= 0:
        return []
    return [value / peak for value in values]


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
    return float(best_bpm)


def is_mixable_intro_from_energies(energies: list[float]) -> bool:
    if len(energies) < 12:
        return False
    active = [value for value in energies if value > 0.08]
    active_ratio = len(active) / len(energies)
    mean_energy = sum(energies) / len(energies)
    peak_energy = max(energies, default=0.0)
    return active_ratio >= 0.35 and mean_energy >= 0.08 and peak_energy >= 0.22


def mixable_region_seconds_from_energies(energies: list[float], *, from_start: bool = True) -> float:
    if not energies:
        return 0.0
    best = 0.0
    max_seconds = int(min(MAX_MIX_SECONDS, len(energies) * ENERGY_FRAME_SECONDS))
    for seconds in range(int(MIX_SECONDS), max_seconds + 1, 4):
        frame_count = max(12, int(seconds / ENERGY_FRAME_SECONDS))
        candidate = energies[:frame_count] if from_start else energies[-frame_count:]
        if is_mixable_intro_from_energies(candidate):
            best = float(seconds)
    return best


def has_mixable_intro(path: Path) -> bool:
    try:
        pcm = decode_audio_pcm(path, max_seconds=INTRO_ANALYSIS_SECONDS)
    except SonoError:
        return False
    return is_mixable_intro_from_energies(energy_envelope(pcm))


def mixable_intro_seconds(path: Path) -> float:
    try:
        pcm = decode_audio_pcm(path, max_seconds=INTRO_ANALYSIS_SECONDS)
    except SonoError:
        return 0.0
    return mixable_region_seconds_from_energies(energy_envelope(pcm), from_start=True)


def mixable_outro_seconds(path: Path, duration_seconds: float | None) -> float:
    if not duration_seconds or duration_seconds <= MIX_SECONDS:
        return 0.0
    start_seconds = max(0.0, duration_seconds - OUTRO_ANALYSIS_SECONDS)
    try:
        pcm = decode_audio_pcm(path, max_seconds=OUTRO_ANALYSIS_SECONDS, start_seconds=start_seconds)
    except SonoError:
        return 0.0
    return mixable_region_seconds_from_energies(energy_envelope(pcm), from_start=False)


def sort_tracks_by_bpm(tracks: list[SonoTrack]) -> list[SonoTrack]:
    return sorted(
        tracks,
        key=lambda track: (
            track.bpm is None,
            track.bpm if track.bpm is not None else 9999.0,
            track.path.name.lower(),
        ),
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
        try:
            bpm = estimator(path)
            duration = probe_duration_seconds(path)
            intro_seconds = mixable_intro_seconds(path)
            outro_seconds = mixable_outro_seconds(path, duration)
        except SonoError as exc:
            bpm = None
            duration = None
            intro_seconds = 0.0
            outro_seconds = 0.0
            errors.append(f"{path.name}: {exc}")
        tracks.append(
            SonoTrack(
                path=path,
                bpm=bpm,
                duration_seconds=duration,
                mixable_intro=intro_seconds >= MIX_SECONDS,
                mixable_intro_seconds=intro_seconds,
                mixable_outro_seconds=outro_seconds,
            )
        )
        if progress:
            progress(f"BPM {index}/{total}", int((index / total) * 100))

    return sort_tracks_by_bpm(tracks), errors
