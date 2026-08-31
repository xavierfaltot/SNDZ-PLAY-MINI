from __future__ import annotations

from statistics import median
from pathlib import Path

from . import bpm as core

# Analyse BPM globale : on échantillonne plusieurs zones réparties sur le
# morceau au lieu de décider à partir du seul début. Cela évite les intros,
# breaks ou premiers coups atypiques qui peuvent faire partir SONO trop vite.
GLOBAL_SAMPLE_FRACTIONS = (0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95)
MIN_GLOBAL_WINDOWS = 3
CONSENSUS_TOLERANCE_BPM = 3.0
VARIABLE_TEMPO_TOLERANCE_BPM = 4.0


def _tempo_family_distance(a: float, b: float) -> float:
    """Distance BPM en tenant compte des ambiguïtés half/double-time."""
    candidates = (a, a / 2.0, a * 2.0)
    return min(abs(candidate - b) for candidate in candidates)


def _estimate_pcm_bpm(
    pcm: bytes,
    min_bpm: int = core.MIN_BPM,
    max_bpm: int = core.MAX_BPM,
) -> float | None:
    onsets = core.onset_envelope(core.energy_envelope(pcm))
    if not onsets or sum(onsets) < 0.2:
        return None

    scores = [(core.bpm_score(onsets, value), value) for value in range(min_bpm, max_bpm + 1)]
    best_score, best_bpm = max(scores, key=lambda item: item[0])
    if best_score <= 0:
        return None
    return core.normalize_bpm_to_range(float(best_bpm))


def _segment_length(duration_seconds: float) -> int:
    # 12 s minimum pour avoir assez de pulsations ; jamais plus long que
    # l'ancienne fenêtre maximale. Sur un long titre, chaque fenêtre reste
    # courte afin que l'analyse globale soit raisonnablement rapide.
    return int(max(12.0, min(float(core.MAX_ANALYSIS_SECONDS), duration_seconds / 9.0)))


def distributed_bpm_estimates(path: Path, duration_seconds: float | None = None) -> list[float]:
    duration = duration_seconds if duration_seconds is not None else core.probe_duration_seconds(path)
    if not duration or duration <= 0:
        value = _estimate_pcm_bpm(core.decode_audio_pcm(path))
        return [value] if value is not None else []

    # Pour les titres courts, analyser pratiquement tout le morceau reste
    # plus fiable que de créer plusieurs petites fenêtres redondantes.
    if duration <= 45.0:
        value = _estimate_pcm_bpm(core.decode_audio_pcm(path, max_seconds=int(max(1.0, duration))))
        return [value] if value is not None else []

    window_seconds = _segment_length(duration)
    max_start = max(0.0, duration - window_seconds)
    estimates: list[float] = []
    seen_starts: set[float] = set()

    for fraction in GLOBAL_SAMPLE_FRACTIONS:
        center = duration * fraction
        start = max(0.0, min(max_start, center - window_seconds / 2.0))
        start = round(start, 3)
        if start in seen_starts:
            continue
        seen_starts.add(start)
        try:
            pcm = core.decode_audio_pcm(path, max_seconds=window_seconds, start_seconds=start)
        except core.SonoError:
            continue
        value = _estimate_pcm_bpm(pcm)
        if value is not None:
            estimates.append(value)

    return estimates


def consensus_bpm(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)

    # Cherche le groupe qui rassemble le plus de fenêtres dans la même
    # famille rythmique, puis prend sa médiane pour ignorer les outliers.
    clusters: list[list[float]] = []
    for anchor in values:
        cluster = [value for value in values if _tempo_family_distance(value, anchor) <= CONSENSUS_TOLERANCE_BPM]
        clusters.append(cluster)

    best = max(clusters, key=lambda cluster: (len(cluster), -max(cluster) + min(cluster)))
    required = MIN_GLOBAL_WINDOWS if len(values) >= MIN_GLOBAL_WINDOWS else 1
    if len(best) < required:
        return None

    # Ramène les valeurs de la famille half/double-time autour de l'ancre
    # dominante avant calcul de médiane.
    anchor = median(best)
    normalized: list[float] = []
    for value in best:
        options = (value, value / 2.0, value * 2.0)
        normalized.append(min(options, key=lambda candidate: abs(candidate - anchor)))

    result = core.normalize_bpm_to_range(float(median(normalized)))
    return round(result, 2) if result is not None else None


def estimate_bpm_global(path: Path) -> float | None:
    return consensus_bpm(distributed_bpm_estimates(path))


def detect_variable_tempo_global(
    path: Path,
    bpm_value: float | None,
    duration_seconds: float | None,
) -> bool:
    if bpm_value is None or not duration_seconds or duration_seconds < 90:
        return False
    estimates = distributed_bpm_estimates(path, duration_seconds)
    if len(estimates) < MIN_GLOBAL_WINDOWS:
        return False
    far = [
        value
        for value in estimates
        if _tempo_family_distance(value, bpm_value) >= VARIABLE_TEMPO_TOLERANCE_BPM
    ]
    return len(far) >= 2 and (len(far) / len(estimates)) >= 0.30


def analyze_track_global(path: Path) -> tuple[core.SonoTrack, str | None]:
    bpm_value: float | None = None
    try:
        duration = core.probe_duration_seconds(path)
        measured_bpm = consensus_bpm(distributed_bpm_estimates(path, duration))
        filename_bpm = core.bpm_from_filename(path)

        # La mesure globale est prioritaire. Le BPM du nom de fichier ne sert
        # que de secours lorsque l'audio ne fournit pas de consensus fiable.
        bpm_value = measured_bpm if measured_bpm is not None else filename_bpm

        key = core.estimate_key(path)
        first_beat = core.first_beat_seconds(path)
        variable_tempo = detect_variable_tempo_global(path, bpm_value, duration)
        intro_seconds = core.mixable_intro_seconds(path)
        outro_seconds, outro_tail_trim = core.mixable_outro_window(path, duration)
        error = None
    except core.SonoError as exc:
        duration = None
        key = ""
        first_beat = 0.0
        variable_tempo = False
        intro_seconds = 0.0
        outro_seconds = 0.0
        outro_tail_trim = 0.0
        error = f"{path.name}: {exc}"

    return (
        core.SonoTrack(
            path=path,
            bpm=bpm_value,
            duration_seconds=duration,
            key=key,
            first_beat_seconds=first_beat,
            variable_tempo=variable_tempo,
            mixable_intro=intro_seconds >= core.MIX_SECONDS,
            mixable_intro_seconds=intro_seconds,
            mixable_outro_seconds=outro_seconds,
            outro_tail_trim_seconds=outro_tail_trim,
        ),
        error,
    )


def analyze_folder_global(
    folder: Path,
    estimator=None,
    progress: core.ProgressCallback | None = None,
) -> tuple[list[core.SonoTrack], list[str]]:
    files = core.find_audio_files(folder)
    if not files:
        raise core.SonoError("No supported sound file")

    tracks: list[core.SonoTrack] = []
    errors: list[str] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        if progress:
            progress(f"BPM GLOBAL {index}/{total}", int(((index - 1) / total) * 100))
        track, error = analyze_track_global(path)
        tracks.append(track)
        if error:
            errors.append(error)
        if progress:
            progress(f"BPM GLOBAL {index}/{total}", int((index / total) * 100))

    deduplicated, removed_pairs = core.deduplicate_tracks(tracks)
    for kept_track, dropped_track in removed_pairs:
        errors.append(f"{dropped_track.path.name}: duplicate of {kept_track.path.name}, skipped")

    return deduplicated, errors


def install() -> None:
    """Installe l'analyse globale avant l'import de l'interface."""
    core.estimate_bpm = estimate_bpm_global
    core.detect_variable_tempo = detect_variable_tempo_global
    core.analyze_track = lambda path, estimator=estimate_bpm_global: analyze_track_global(path)
    core.analyze_folder = analyze_folder_global
