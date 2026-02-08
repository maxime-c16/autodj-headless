"""
DSP Configuration Module
=========================

Centralizes all DSP parameters that were previously hardcoded across
spectral.py, loudness.py, and adaptive_eq.py modules.

Provides a single DSPConfig dataclass that the pipeline passes to
all analysis functions, ensuring consistent parameters globally.

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

from dataclasses import dataclass


@dataclass
class DSPConfig:
    """Global DSP configuration for all analysis modules.

    Attributes:
        sample_rate: Audio sample rate in Hz
        fft_size: FFT window size in samples
        hop_length: Hop size in samples between frames
        window: FFT window type (e.g., "hann")

        # Frequency band boundaries (Hz)
        bass_freq_low: Low end of bass band
        bass_freq_high: High end of bass band
        mid_freq_low: Low end of mid band
        mid_freq_high: High end of mid band
        treble_freq_low: Low end of treble band
        treble_freq_high: High end of treble band

        # Detection thresholds
        energy_threshold: Energy peak detection threshold (0.0-1.0)
        kick_threshold: Kick detection threshold
        quiet_threshold: Below this = silence

        # Loudness (ITU-R BS.1770-4)
        loudness_sample_rate: Sample rate for K-weighting (48kHz standard)
        momentary_block_ms: Momentary loudness block size
        short_term_block_ms: Short-term loudness block size
        block_overlap: Overlap fraction between blocks
        absolute_gate_lufs: Absolute silence gate
        true_peak_oversample: Oversampling factor for true peak

        # Adaptive EQ
        eq_sensitivity: EQ correction sensitivity (0.0-1.0)
        eq_max_gain_db: Maximum EQ boost/cut in dB
        eq_reference_bass: Target bass energy fraction
        eq_reference_mid: Target mid energy fraction
        eq_reference_treble: Target treble energy fraction
    """

    # Core audio
    sample_rate: int = 44100
    fft_size: int = 2048
    hop_length: int = 512
    window: str = "hann"

    # Frequency bands (Hz)
    bass_freq_low: float = 20.0
    bass_freq_high: float = 200.0
    mid_freq_low: float = 200.0
    mid_freq_high: float = 2000.0
    treble_freq_low: float = 2000.0
    treble_freq_high: float = 20000.0

    # Detection thresholds
    energy_threshold: float = 0.7
    kick_threshold: float = 0.75
    quiet_threshold: float = 0.05

    # Loudness
    loudness_sample_rate: int = 48000
    momentary_block_ms: int = 400
    short_term_block_ms: int = 3000
    block_overlap: float = 0.75
    absolute_gate_lufs: float = -70.0
    true_peak_oversample: int = 4

    # Adaptive EQ
    eq_sensitivity: float = 0.7
    eq_max_gain_db: float = 6.0
    eq_reference_bass: float = 0.35
    eq_reference_mid: float = 0.40
    eq_reference_treble: float = 0.25

    @property
    def fft_overlap(self) -> int:
        """Number of overlapping samples between FFT frames."""
        return self.fft_size - self.hop_length
