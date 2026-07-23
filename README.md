# SNDZ PLAY MINI 2.0

SNDZ PLAY MINI is a tiny desktop audio player for local sound folders.

Click the logo, choose a folder, then the app analyzes local audio tempo immediately. Press the play icon to play the list from lowest BPM to highest BPM, so the energy climbs. Press next to jump forward. While playing, drop an audio file on the logo to make it the next track.

The three bottom buttons choose the BPM start point:

```text
LOW  -> start from the calmest/lowest BPM track
HALF -> start from the middle of the detected BPM climb
HIGH -> start from the first high-BPM section
```

The app stays intentionally small:

- logo folder pick
- automatic BPM analysis with range normalization to avoid half/double BPM mistakes
- first-beat cue detection for an internal beatgrid start
- rough local key detection for harmonic mix assist
- variable-tempo flagging for disco, funk, and live-feeling tracks
- sorted queue
- live drop-to-logo next-track queue
- icon controls for play and next
- LOW / HALF / HIGH start buttons
- looping from the calmest track after the highest track
- adaptive crossfade
- smart playback EQ and loudness matching when `ffplay` is available
- current track title only

Mixes stay short by default, then get longer when the current outro and next intro have usable music beds and the BPMs are close. If a long transition is not possible, the player uses zero transition: it lets the current track finish and starts the next one cleanly. A small local mix-assist layer applies playback-only EQ and loudness matching: sub-bass cleanup, high cut, gentle compression, BPM-aware low/presence gains, and `loudnorm` so tracks come out at a more consistent perceived volume. It does not write analysis files or modify the source sounds.

It does not tag, rewrite, beatmatch, or alter source files.

## Requirements

```bash
python3
ffmpeg
ffprobe
```

`ffplay` is preferred for playback because it supports the EQ/filter chain. macOS `afplay` is used as fallback when `ffplay` is unavailable.

## Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_sndz_mini.py
```

Or double-click:

```text
SNDZ PLAY MINI.command
```

## macOS Desktop App

```bash
./scripts/create_desktop_app.command
```

That creates:

```text
~/Desktop/SNDZ PLAY MINI.app
```

## Supported Audio

```text
mp3, wav, flac, aiff, aac, m4a, mp4
```

## Credits

Conception product and art direction: Xavier Faltot.

Development: Codex, OpenAI coding assistant.

Project: RUSH OPERATOR.
