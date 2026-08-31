# SONO PLAY MINI 2.0

SONO PLAY MINI is a tiny desktop audio player for local sound folders.

## Download for macOS

**[DOWNLOAD SONO PLAY MINI for macOS](https://toutvabiensepasser.com/SONO-PLAY-MINI-macOS.dmg)**

Click the logo, choose a folder, then the app analyzes local audio tempo immediately. Press the play icon to play the list from lowest BPM to highest BPM, so the energy climbs. Playback always starts from the calmest track. Press next to jump forward. While playing, drop audio files on the logo: the first dropped file becomes the next track, and the other dropped files are analyzed and diluted into the BPM flow.

The app stays intentionally small:

- logo folder pick
- automatic BPM analysis with range normalization to avoid half/double BPM mistakes
- filename BPM import, for names like `shazam_youtube_all_about_u_original_mix_02 [084 BPM]`
- first-beat cue detection for an internal beatgrid start
- rough local key detection for harmonic mix assist
- variable-tempo flagging for disco, funk, and live-feeling tracks
- sorted queue
- automatic duplicate detection: the same sound saved twice under different names (auto-numbered or "copy" suffixes) is only counted once, keeping the best-quality copy
- live drop-to-logo queue: first drop next, remaining drops diluted by BPM
- icon controls for play and next
- looping from the calmest track after the highest track
- adaptive crossfade, armed off the player's actual start signal (not a guessed timer) to keep the transition on time
- best-effort beat alignment on the crossfade: the trigger point is nudged by up to half a beat, using each track's BPM and first-beat cue, so the blend starts in phase instead of at a blind time offset (no time-stretching or pitch-shifting: tempos still drift apart if they differ, but the transition itself starts on the beat)
- at most two tracks ever play at once: starting a new track always cuts anything older than the one it is crossfading with
- vocal-band gate on the crossfade: intro/outro regions dominated by energy in the ~300-3400Hz vocal range are never offered up for mixing, so two vocal lines don't overlap
- when the very ending of a track is vocal, the outro search backs off to find an instrumental handle a bit earlier instead of cancelling the mix outright; the vocal tail past that handle is cut once the next track takes over rather than played out underneath it
- gapless preroll when no real mix is offered: the next track still starts a third of a second early, just enough to absorb process-launch latency, so there is no silent gap between tracks
- smart playback EQ and loudness matching when `ffplay` is available
- LED-style now-playing screen under PLAY/NEXT showing the track title only, nothing else
- no repeated title before every other title in the cycle has played

Mixes are short and capped low (up to 12 seconds, and much less when tempos differ or a section looks vocal-heavy), so tracks mostly play out in full instead of blending for long stretches. If a clean transition is not possible, the player skips the real mix but still starts the next track a third of a second early (gapless preroll), so the next player's own startup latency never reads as a beat of silence between tracks. A small local mix-assist layer applies playback-only EQ and loudness matching: sub-bass cleanup, high cut, gentle compression, BPM-aware low/presence gains, and `loudnorm` so tracks come out at a more consistent perceived volume. It does not write analysis files or modify the source sounds.

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
SONO PLAY MINI.command
```

## macOS Desktop App

Download the ready-to-use macOS disk image:

**[SONO-PLAY-MINI-macOS.dmg](https://toutvabiensepasser.com/SONO-PLAY-MINI-macOS.dmg)**

To build the desktop app from source:

```bash
./scripts/create_desktop_app.command
```

That creates:

```text
~/Desktop/SONO PLAY MINI.app
```

## Supported Audio

```text
mp3, wav, flac, aiff, aac, m4a, mp4
```

## Credits

Conception product and art direction: Xavier Faltot.

Development: Codex, OpenAI coding assistant.

Project: RUSH OPERATOR.
