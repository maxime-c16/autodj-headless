"""
MIR Analysis Module: Extract BPM, key, cue points, loudness, and EQ from audio.

Phases:
- Phase 1: BPM detection (aubio/essentia), key detection, cue points
- Phase 2: Harmonic mixing (Camelot wheel compatibility)
- Phase 3: Spectral analysis (frequency content, smart cues)
- Phase 4: Loudness (ITU-R BS.1770-4 LUFS), adaptive EQ, unified pipeline

Per SPEC.md § 2.1:
- One file at a time
- Max 30 sec per track
- Peak memory ≤ 512 MiB
"""

__all__ = [
    "bpm",
    "key",
    "cues",
    "harmonic",
    "spectral",
    "loudness",
    "adaptive_eq",
    "pipeline",
    "audio_loader",
    "dsp_config",
]
