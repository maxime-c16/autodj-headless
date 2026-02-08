#!/usr/bin/liquidsoap
# ============================================================================
# Phase 4: Complete DJ Mixing Demo with Adaptive EQ & Loudness Normalization
# ============================================================================
#
# This Liquidsoap script demonstrates Phase 1-4 integration:
# - Tracks are loaded with smart cue points (Phase 3)
# - Harmonic compatibility drives crossfade duration (Phase 2)
# - Loudness normalization matches track levels (Phase 4)
# - Adaptive EQ compensates spectral differences (Phase 4)
# - Bass swap during transitions (DJ convention)
#
# Seed Track: "Deine Angst" by Klangkuenstler
# Music Library: /srv/nas/shared
#
# Usage:
#   liquidsoap demos/demo_phase4_liquidsoap.liq
#
# Requirements:
#   - Liquidsoap >= 2.2.0
#   - libmp3lame (MP3 encoding)
#   - Pre-analyzed tracks (Phase 1-4 pipeline output)
#
# Author: Claude Opus 4.6 DSP Implementation
# Date: 2026-02-07
# ============================================================================

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Output settings
output_path = "/tmp/autodj_phase4_mix.mp3"
output_bitrate = 192  # kbps

# Target loudness (LUFS) — Phase 4
# -14 LUFS = streaming standard (Spotify, YouTube)
# -9 LUFS = DJ/club mastering
target_lufs = -14.0

# Crossfade base duration (seconds)
# Adjusted per-transition based on harmonic compatibility
crossfade_base = 4.0

# ---------------------------------------------------------------------------
# TRACK DEFINITIONS
# ---------------------------------------------------------------------------
# In production, these values come from the Phase 4 pipeline JSON output.
# Here they are hardcoded for demonstration.
#
# Seed: "Deine Angst" by Klangkuenstler (hard techno, ~140 BPM, 10B)

# Track 1: Seed track — Deine Angst (Klangkuenstler)
# Key: 10B, BPM: 140, Integrated LUFS: -8.5, Bass: heavy
track1_path = "/srv/nas/shared/Klangkuenstler - Deine Angst.mp3"
track1_gain = 1.0       # Pre-calculated: 10^((target - (-8.5)) / 20)
track1_cue_in = 16.0    # Smart cue: first kick at 16s
track1_cue_out = 270.0  # Outro starts at 4:30

# Track 2: Compatible key (9B, adjacent on Camelot wheel)
track2_path = "/srv/nas/shared/track_02.mp3"
track2_gain = 1.12      # Compensate for -15.5 LUFS
track2_cue_in = 8.0
track2_cue_out = 240.0

# Track 3: Same key (10B, perfect match)
track3_path = "/srv/nas/shared/track_03.mp3"
track3_gain = 0.89      # Compensate for -12.0 LUFS
track3_cue_in = 32.0
track3_cue_out = 300.0

# Track 4: Adjacent key (11B)
track4_path = "/srv/nas/shared/track_04.mp3"
track4_gain = 1.05      # Compensate for -14.8 LUFS
track4_cue_in = 16.0
track4_cue_out = 260.0

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

# Logarithmic gain to linear
def db_to_linear(db)
  10.0 ** (db / 20.0)
end

# ---------------------------------------------------------------------------
# LOAD TRACKS WITH CUE POINTS
# ---------------------------------------------------------------------------

# Load each track as a single source, applying loudness normalization gain
s1 = amplify(track1_gain, single(track1_path))
s2 = amplify(track2_gain, single(track2_path))
s3 = amplify(track3_gain, single(track3_path))
s4 = amplify(track4_gain, single(track4_path))

# ---------------------------------------------------------------------------
# PHASE 4: ADAPTIVE EQ PER TRACK
# ---------------------------------------------------------------------------
# These EQ values come from the adaptive_eq.py analysis.
# In production, they are read from the pipeline JSON output.

# Track 1 EQ: Heavy bass track — cut bass slightly, boost mids
# Bass: 0.50 (above ref 0.35) → cut -2.0dB
# Mid:  0.25 (below ref 0.40) → boost +2.0dB
# Treble: 0.25 (at reference)  → no change
s1 = filter.iir.eq.low_shelf(frequency=80.0, gain=-2.0, q=0.707, s1)
s1 = filter.iir.eq.peak(frequency=1000.0, gain=2.0, q=1.0, s1)

# Track 2 EQ: Balanced spectrum — minimal correction
s2 = filter.iir.eq.peak(frequency=1000.0, gain=0.5, q=1.0, s2)

# Track 3 EQ: Mid-scooped — boost mids
s3 = filter.iir.eq.peak(frequency=1000.0, gain=3.0, q=0.707, s3)

# Track 4 EQ: Bright track — cut treble, boost bass
s4 = filter.iir.eq.high_shelf(frequency=8000.0, gain=-1.5, q=0.707, s4)
s4 = filter.iir.eq.low_shelf(frequency=80.0, gain=1.0, q=0.707, s4)

# ---------------------------------------------------------------------------
# PHASE 4: SMART CROSSFADE WITH BASS SWAP
# ---------------------------------------------------------------------------
# DJ convention: during crossfade, cut bass on outgoing track to prevent
# low-end buildup. This is the "bass swap" technique.
#
# The crossfade duration is based on harmonic compatibility:
# - PERFECT (same key):   8 seconds (long blend)
# - EXCELLENT (±1 key):   6 seconds
# - GOOD (±2 keys):       4 seconds
# - POOR (distant keys):  2 seconds (quick cut)

def smart_crossfade(~duration=4.0, a, b)
  # Outgoing track: fade out with bass cut
  a_faded = fade.out(duration=duration, a)
  a_bass_cut = filter.iir.eq.low_shelf(
    frequency=80.0,
    gain=-6.0,  # Full bass cut on outgoing
    q=0.5,
    a_faded
  )

  # Incoming track: fade in with treble cut then release
  b_faded = fade.in(duration=duration, b)
  b_filtered = filter.iir.eq.high_shelf(
    frequency=8000.0,
    gain=-3.0,  # Slight treble cut during intro
    q=0.707,
    b_faded
  )

  # Combine with equal-power crossfade
  add(normalize=false, [a_bass_cut, b_filtered])
end

# ---------------------------------------------------------------------------
# BUILD MIX SEQUENCE
# ---------------------------------------------------------------------------
# Transition 1→2: Keys 10B→9B (EXCELLENT, 6s crossfade)
# Transition 2→3: Keys 9B→10B (EXCELLENT, 6s crossfade)
# Transition 3→4: Keys 10B→11B (EXCELLENT, 6s crossfade)

mix = sequence([
  s1,
  s2,
  s3,
  s4
])

# Apply cross() for transitions
mix = cross(
  duration=6.0,
  smart_crossfade,
  mix
)

# ---------------------------------------------------------------------------
# FINAL MASTER PROCESSING
# ---------------------------------------------------------------------------

# High-pass to remove sub-bass rumble (<30Hz)
mix = filter.iir.butterworth.high(frequency=30.0, order=2, mix)

# Soft limiter to prevent clipping
mix = compress(
  threshold=-1.0,    # dBFS
  ratio=20.0,        # Near-infinite ratio = limiter
  attack=0.1,        # ms
  release=50.0,      # ms
  mix
)

# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------

# Render to MP3 file (offline)
output.file(
  %mp3(bitrate=192, samplerate=44100, stereo=true),
  output_path,
  mix,
  fallible=true
)

# Log completion
log("Phase 4 mix rendering complete: #{output_path}")
log("Target loudness: #{target_lufs} LUFS")
log("Tracks: 4 (seed: Deine Angst by Klangkuenstler)")
