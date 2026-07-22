# SNDZ PLAY MINI

SNDZ PLAY MINI is a tiny desktop audio player for local sound folders.

Click the logo, choose a folder, then the app analyzes local audio tempo immediately. Press the play icon to play the list from lowest BPM to highest BPM, so the energy climbs. Press next to jump forward.

The app stays intentionally small:

- logo folder pick
- automatic BPM analysis
- sorted queue
- icon controls for play and next
- adaptive crossfade
- smart playback EQ when `ffplay` is available
- current track title only

Mixes stay short by default, then get longer when the current outro and next intro have usable music beds and the BPMs are close. A small local mix-assist layer applies playback-only EQ: sub-bass cleanup, high cut, gentle compression, and BPM-aware low/presence gains. It does not write analysis files or modify the source sounds.

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
