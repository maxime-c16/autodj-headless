"""
MIR Analysis Module: Extract BPM, key, and cue points from audio files.

Per SPEC.md § 2.1:
- One file at a time
- Max 30 sec per track
- Peak memory ≤ 512 MiB
"""

__all__ = ["bpm", "key", "cues"]
