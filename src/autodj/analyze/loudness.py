"""
Phase 4: Loudness Measurement Module (ITU-R BS.1770-4)
=======================================================

Implements the EBU R 128 / ITU-R BS.1770-4 loudness measurement standard
for professional DJ mixing. Provides integrated, short-term, and momentary
loudness measurements, true peak metering, and loudness range calculation.

Theory:
    The ITU-R BS.1770-4 standard defines loudness measurement using:
    1. K-weighting pre-filter (two cascaded biquad stages)
    2. Mean-square energy calculation per 400ms blocks
    3. Gated loudness integration (absolute -70 LUFS gate, relative -10 LU gate)

    K-weighting accounts for the frequency response of the human head,
    applying a high-shelf boost around 2kHz and a high-pass filter
    to roll off low frequencies.

    Reference: ITU-R BS.1770-4 (10/2015)
    Reference: EBU R 128 (2020)

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import gc
import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import scipy.signal as signal
    import scipy.io.wavfile as wavfile
except ImportError:
    raise ImportError("scipy required: pip install scipy")

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

SAMPLE_RATE = 48000  # ITU-R BS.1770 specifies 48kHz for filter coefficients
SAMPLE_RATE_44100 = 44100  # Common audio sample rate

# Block sizes per ITU-R BS.1770-4
MOMENTARY_BLOCK_MS = 400   # 400ms momentary loudness blocks
SHORT_TERM_BLOCK_MS = 3000  # 3-second short-term loudness
OVERLAP_FRACTION = 0.75     # 75% overlap between blocks

# Gating thresholds
ABSOLUTE_GATE_LUFS = -70.0   # Absolute silence gate
RELATIVE_GATE_LU = -10.0     # Relative gate (below ungated loudness)

# LUFS offset constant from ITU-R BS.1770-4
LUFS_OFFSET = -0.691

# Channel weights (for stereo: left=1.0, right=1.0)
CHANNEL_WEIGHTS = {
    1: [1.0],             # Mono
    2: [1.0, 1.0],        # Stereo (L, R)
    6: [1.0, 1.0, 1.0, 0.0, 1.41, 1.41],  # 5.1 (L, R, C, LFE, Ls, Rs)
}

# True peak oversampling factor
TRUE_PEAK_OVERSAMPLE = 4

# Target loudness for streaming platforms
TARGET_LUFS_STREAMING = -14.0   # Spotify, YouTube
TARGET_LUFS_BROADCAST = -23.0   # EBU R 128 broadcast
TARGET_LUFS_DJ = -9.0           # DJ mastering (louder)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LoudnessProfile:
    """Complete loudness analysis result for a track.

    Attributes:
        integrated_lufs: Overall loudness in LUFS (gated per BS.1770-4)
        short_term_lufs: List of 3-second short-term loudness values
        momentary_lufs: List of 400ms momentary loudness values
        true_peak_dbtp: True peak level in dBTP (oversampled)
        loudness_range_lu: Loudness range in LU (dynamic range)
        sample_peak_db: Sample peak level in dBFS (non-oversampled)
        duration_seconds: Track duration
        target_gain_db: Gain needed to reach target LUFS
        target_lufs: Target LUFS used for gain calculation
        max_short_term_lufs: Maximum short-term loudness
        min_short_term_lufs: Minimum short-term loudness (above gate)
        ungated_lufs: Integrated loudness without gating
    """
    integrated_lufs: float
    short_term_lufs: List[float] = field(default_factory=list)
    momentary_lufs: List[float] = field(default_factory=list)
    true_peak_dbtp: float = 0.0
    loudness_range_lu: float = 0.0
    sample_peak_db: float = 0.0
    duration_seconds: float = 0.0
    target_gain_db: float = 0.0
    target_lufs: float = TARGET_LUFS_STREAMING
    max_short_term_lufs: float = -np.inf
    min_short_term_lufs: float = np.inf
    ungated_lufs: float = -np.inf

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "integrated_lufs": round(self.integrated_lufs, 2),
            "short_term_lufs": [round(v, 2) for v in self.short_term_lufs],
            "momentary_lufs": [round(v, 2) for v in self.momentary_lufs],
            "true_peak_dbtp": round(self.true_peak_dbtp, 2),
            "loudness_range_lu": round(self.loudness_range_lu, 2),
            "sample_peak_db": round(self.sample_peak_db, 2),
            "duration_seconds": round(self.duration_seconds, 2),
            "target_gain_db": round(self.target_gain_db, 2),
            "target_lufs": round(self.target_lufs, 2),
            "max_short_term_lufs": round(self.max_short_term_lufs, 2),
            "min_short_term_lufs": round(self.min_short_term_lufs, 2),
            "ungated_lufs": round(self.ungated_lufs, 2),
        }


# ============================================================================
# K-WEIGHTING FILTER (ITU-R BS.1770-4)
# ============================================================================

def design_k_weighting_filters(
    sample_rate: int = SAMPLE_RATE,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Design the two-stage K-weighting filter per ITU-R BS.1770-4.

    Stage 1: High-shelf filter modeling the acoustic effect of the human head.
             Provides ~4dB boost above 2kHz.
    Stage 2: High-pass filter (RLB weighting) to attenuate low frequencies.
             Approximately -3dB at 100Hz.

    The filter coefficients are specified at 48kHz in the ITU standard.
    For other sample rates, we use bilinear transform with frequency warping.

    Args:
        sample_rate: Audio sample rate in Hz

    Returns:
        Tuple of (b1, a1, b2, a2) where:
            b1, a1: Stage 1 (head-related shelf) numerator/denominator
            b2, a2: Stage 2 (RLB high-pass) numerator/denominator
    """
    if sample_rate == 48000:
        # Pre-computed coefficients from ITU-R BS.1770-4 Table 1
        b1 = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
        a1 = np.array([1.0, -1.69065929318241, 0.73248077421585])

        b2 = np.array([1.0, -2.0, 1.0])
        a2 = np.array([1.0, -1.99004745483398, 0.99007225036621])
    elif sample_rate == 44100:
        # Coefficients for 44.1kHz (derived via bilinear transform)
        b1 = np.array([1.53090959966709, -2.65116903584775, 1.16907559409601])
        a1 = np.array([1.0, -1.66375011258542, 0.71265486718971])

        b2 = np.array([1.0, -2.0, 1.0])
        a2 = np.array([1.0, -1.98916967014199, 0.98919925044498])
    else:
        # Generic design using bilinear transform for arbitrary sample rates
        b1, a1 = _design_head_shelf(sample_rate)
        b2, a2 = _design_rlb_highpass(sample_rate)

    return b1, a1, b2, a2


def _design_head_shelf(sample_rate: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Design Stage 1 head-related shelf filter for arbitrary sample rate.

    Uses a peaking EQ approximation centered at ~1500Hz with Q~0.7
    and a high-shelf at ~1681Hz with ~4dB gain.

    Args:
        sample_rate: Sample rate in Hz

    Returns:
        Tuple of (b, a) filter coefficients
    """
    # High-shelf filter: fc=1500Hz, gain=+4dB, Q=0.7071 (Butterworth)
    fc = 1681.974450955533
    gain_db = 3.999843853973347
    q = 0.7071752369554196

    A = 10 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * fc / sample_rate
    alpha = np.sin(w0) / (2.0 * q)

    cos_w0 = np.cos(w0)
    sqrt_A = np.sqrt(A)
    two_sqrt_A_alpha = 2.0 * sqrt_A * alpha

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + two_sqrt_A_alpha)
    b1_coeff = -2.0 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - two_sqrt_A_alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + two_sqrt_A_alpha
    a1_coeff = 2.0 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - two_sqrt_A_alpha

    b = np.array([b0 / a0, b1_coeff / a0, b2 / a0])
    a = np.array([1.0, a1_coeff / a0, a2 / a0])
    return b, a


def _design_rlb_highpass(sample_rate: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Design Stage 2 RLB (Revised Low-frequency B-weighting) high-pass filter.

    Second-order high-pass at ~38.1Hz (the RLB curve).

    Args:
        sample_rate: Sample rate in Hz

    Returns:
        Tuple of (b, a) filter coefficients
    """
    fc = 38.13547087602444
    q = 0.5003270373238773

    w0 = 2.0 * np.pi * fc / sample_rate
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)

    b0 = (1.0 + cos_w0) / 2.0
    b1_coeff = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1_coeff = -2.0 * cos_w0
    a2 = 1.0 - alpha

    b = np.array([b0 / a0, b1_coeff / a0, b2 / a0])
    a = np.array([1.0, a1_coeff / a0, a2 / a0])
    return b, a


def apply_k_weighting(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Apply K-weighting filter to audio signal.

    Cascades two IIR filter stages:
    1. Head-related high-shelf (~+4dB above 2kHz)
    2. RLB high-pass (roll off below ~100Hz)

    Args:
        audio: Input audio signal (1D or 2D: samples x channels)
        sample_rate: Audio sample rate in Hz

    Returns:
        K-weighted audio signal (same shape as input)
    """
    b1, a1, b2, a2 = design_k_weighting_filters(sample_rate)

    if audio.ndim == 1:
        # Mono: apply both stages in cascade
        stage1 = signal.lfilter(b1, a1, audio)
        return signal.lfilter(b2, a2, stage1)
    else:
        # Multi-channel: filter each channel independently
        result = np.zeros_like(audio)
        for ch in range(audio.shape[1]):
            stage1 = signal.lfilter(b1, a1, audio[:, ch])
            result[:, ch] = signal.lfilter(b2, a2, stage1)
        return result


# ============================================================================
# BLOCK-BASED LOUDNESS CALCULATION
# ============================================================================

def compute_block_loudness(
    audio: np.ndarray,
    sample_rate: int,
    block_ms: int = MOMENTARY_BLOCK_MS,
    overlap: float = OVERLAP_FRACTION,
    channel_weights: Optional[List[float]] = None,
) -> np.ndarray:
    """
    Compute block-based loudness per ITU-R BS.1770-4.

    Divides K-weighted audio into overlapping blocks and computes
    mean-square energy per block, then converts to LUFS.

    Args:
        audio: K-weighted audio (1D mono or 2D multi-channel)
        sample_rate: Sample rate in Hz
        block_ms: Block duration in milliseconds (400 or 3000)
        overlap: Overlap fraction between blocks (0.75 = 75%)
        channel_weights: Per-channel gain weights (None = equal weighting)

    Returns:
        1D array of LUFS values per block
    """
    block_samples = int(sample_rate * block_ms / 1000.0)
    hop_samples = int(block_samples * (1.0 - overlap))

    if hop_samples < 1:
        hop_samples = 1

    # Ensure 2D (samples x channels)
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]

    n_channels = audio.shape[1]
    n_samples = audio.shape[0]

    if channel_weights is None:
        channel_weights = [1.0] * n_channels

    # Compute block mean-square per channel
    n_blocks = max(1, (n_samples - block_samples) // hop_samples + 1)
    block_lufs = np.full(n_blocks, -np.inf)

    for b in range(n_blocks):
        start = b * hop_samples
        end = start + block_samples
        if end > n_samples:
            break

        block = audio[start:end, :]

        # Weighted mean-square across channels
        weighted_ms = 0.0
        for ch in range(n_channels):
            ms = np.mean(block[:, ch] ** 2)
            weighted_ms += channel_weights[ch] * ms

        if weighted_ms > 0:
            block_lufs[b] = LUFS_OFFSET + 10.0 * np.log10(weighted_ms)

    return block_lufs


def compute_gated_loudness(block_lufs: np.ndarray) -> float:
    """
    Compute gated integrated loudness per ITU-R BS.1770-4.

    Two-stage gating:
    1. Absolute gate: discard blocks below -70 LUFS
    2. Relative gate: compute ungated mean, then discard blocks
       more than 10 LU below that mean

    Args:
        block_lufs: Array of per-block LUFS values

    Returns:
        Gated integrated loudness in LUFS
    """
    # Stage 1: Absolute gate at -70 LUFS
    valid = block_lufs[block_lufs > ABSOLUTE_GATE_LUFS]

    if len(valid) == 0:
        return -np.inf

    # Convert back to linear for averaging
    linear_values = 10.0 ** ((valid - LUFS_OFFSET) / 10.0)
    ungated_mean = np.mean(linear_values)
    ungated_lufs = LUFS_OFFSET + 10.0 * np.log10(ungated_mean)

    # Stage 2: Relative gate at ungated - 10 LU
    relative_gate = ungated_lufs + RELATIVE_GATE_LU

    gated = valid[valid > relative_gate]

    if len(gated) == 0:
        return ungated_lufs

    linear_gated = 10.0 ** ((gated - LUFS_OFFSET) / 10.0)
    gated_mean = np.mean(linear_gated)
    integrated = LUFS_OFFSET + 10.0 * np.log10(gated_mean)

    return float(integrated)


# ============================================================================
# TRUE PEAK METERING
# ============================================================================

def measure_true_peak(
    audio: np.ndarray,
    sample_rate: int,
    oversample_factor: int = TRUE_PEAK_OVERSAMPLE,
) -> float:
    """
    Measure true peak level using oversampled interpolation.

    Per ITU-R BS.1770-4, true peak is measured by oversampling the signal
    (typically 4x) and finding the absolute maximum. This catches inter-sample
    peaks that exceed the sample values.

    Args:
        audio: Input audio signal (1D or 2D)
        sample_rate: Original sample rate
        oversample_factor: Oversampling factor (4 per ITU standard)

    Returns:
        True peak level in dBTP (dB True Peak, relative to full scale)
    """
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]

    max_peak = 0.0

    for ch in range(audio.shape[1]):
        channel_data = audio[:, ch]

        # Process in chunks to save memory (512MB container limit)
        chunk_size = sample_rate * 10  # 10 seconds at a time
        for start in range(0, len(channel_data), chunk_size):
            end = min(start + chunk_size, len(channel_data))
            chunk = channel_data[start:end]

            # Upsample using polyphase resampling
            upsampled = signal.resample_poly(
                chunk, oversample_factor, 1
            )
            chunk_peak = np.max(np.abs(upsampled))
            max_peak = max(max_peak, chunk_peak)

    if max_peak > 0:
        return float(20.0 * np.log10(max_peak))
    return -np.inf


def measure_sample_peak(audio: np.ndarray) -> float:
    """
    Measure sample peak level (non-oversampled).

    Args:
        audio: Input audio signal

    Returns:
        Sample peak in dBFS
    """
    peak = np.max(np.abs(audio))
    if peak > 0:
        return float(20.0 * np.log10(peak))
    return -np.inf


# ============================================================================
# LOUDNESS RANGE (LRA)
# ============================================================================

def compute_loudness_range(short_term_lufs: np.ndarray) -> float:
    """
    Compute Loudness Range (LRA) per EBU R 128 / EBU Tech 3342.

    LRA measures the dynamic range of a track using the distribution
    of short-term loudness values. It's defined as the difference
    between the 95th and 10th percentiles of gated short-term loudness.

    Args:
        short_term_lufs: Array of 3-second short-term LUFS values

    Returns:
        Loudness range in LU (Loudness Units)
    """
    # Apply absolute gate
    valid = short_term_lufs[short_term_lufs > ABSOLUTE_GATE_LUFS]

    if len(valid) < 2:
        return 0.0

    # Apply relative gate (ungated mean - 20 LU for LRA, per EBU Tech 3342)
    linear_values = 10.0 ** ((valid - LUFS_OFFSET) / 10.0)
    ungated_mean = np.mean(linear_values)
    ungated_lufs = LUFS_OFFSET + 10.0 * np.log10(ungated_mean)

    relative_gate_lra = ungated_lufs - 20.0  # LRA uses -20 LU gate
    gated = valid[valid > relative_gate_lra]

    if len(gated) < 2:
        return 0.0

    # LRA = 95th percentile - 10th percentile
    p95 = float(np.percentile(gated, 95))
    p10 = float(np.percentile(gated, 10))

    return max(0.0, p95 - p10)


# ============================================================================
# AUDIO LOADING (Memory-Efficient)
# ============================================================================

def load_audio_for_loudness(
    file_path: str,
    target_sr: Optional[int] = None,
) -> Tuple[np.ndarray, int]:
    """
    Load audio file for loudness analysis.

    Memory-efficient loading: uses scipy for WAV, librosa fallback for others.
    Maintains original channel count for proper loudness calculation.

    Args:
        file_path: Path to audio file
        target_sr: Target sample rate (None = keep original for WAV, 48000 for others)

    Returns:
        Tuple of (audio_data, sample_rate)
        audio_data shape: (samples,) for mono or (samples, channels) for stereo

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If format not supported
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    suffix = path.suffix.lower()

    try:
        if suffix == ".wav":
            sr, audio = wavfile.read(file_path)
            # Normalize to float32 [-1.0, 1.0]
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0
            elif audio.dtype == np.float32:
                pass
            elif audio.dtype == np.float64:
                audio = audio.astype(np.float32)
            else:
                audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max

            if target_sr and sr != target_sr:
                if audio.ndim == 1:
                    audio = signal.resample_poly(
                        audio, target_sr, sr
                    ).astype(np.float32)
                else:
                    resampled = np.zeros(
                        (int(len(audio) * target_sr / sr), audio.shape[1]),
                        dtype=np.float32,
                    )
                    for ch in range(audio.shape[1]):
                        resampled[:, ch] = signal.resample_poly(
                            audio[:, ch], target_sr, sr
                        ).astype(np.float32)
                    audio = resampled
                sr = target_sr

            return audio, sr

        else:
            # Non-WAV: use librosa (loads as mono by default)
            try:
                import librosa
                sr_target = target_sr or SAMPLE_RATE
                audio, sr = librosa.load(
                    file_path, sr=sr_target, mono=False
                )
                # librosa returns (channels, samples) for stereo
                if audio.ndim == 2:
                    audio = audio.T  # Convert to (samples, channels)
                return audio.astype(np.float32), sr
            except ImportError:
                raise ValueError(
                    f"librosa required for {suffix} files. pip install librosa"
                )

    except Exception as e:
        raise ValueError(f"Failed to load {file_path}: {e}")


# ============================================================================
# MAIN ANALYSIS FUNCTION
# ============================================================================

def analyze_loudness(
    filepath: str,
    target_lufs: float = TARGET_LUFS_STREAMING,
    compute_true_peak: bool = True,
    audio_data: Optional[Tuple[np.ndarray, int]] = None,
) -> LoudnessProfile:
    """
    Perform complete loudness analysis per ITU-R BS.1770-4.

    Pipeline:
    1. Load audio (preserve channels)
    2. Apply K-weighting filter
    3. Compute momentary loudness (400ms blocks, 75% overlap)
    4. Compute short-term loudness (3s blocks, 75% overlap)
    5. Compute gated integrated loudness
    6. Measure true peak (4x oversampled)
    7. Compute loudness range (LRA)

    Args:
        filepath: Path to audio file
        target_lufs: Target loudness for gain calculation (default -14 LUFS)
        compute_true_peak: Whether to compute true peak (slower but accurate)
        audio_data: Optional pre-loaded (audio, sr) tuple from AudioCache.
                    When provided, skips disk loading.

    Returns:
        LoudnessProfile with all measurements

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If audio format not supported
    """
    logger.info(f"Analyzing loudness: {filepath}")

    # Load audio (or use cached)
    if audio_data is not None:
        audio, sr = audio_data
    else:
        audio, sr = load_audio_for_loudness(filepath)
    duration = len(audio) / sr if audio.ndim == 1 else audio.shape[0] / sr

    logger.debug(
        f"Loaded: {duration:.1f}s, {sr}Hz, "
        f"{'mono' if audio.ndim == 1 else f'{audio.shape[1]}ch'}"
    )

    # Apply K-weighting
    k_weighted = apply_k_weighting(audio, sr)

    # Compute momentary loudness (400ms blocks)
    momentary = compute_block_loudness(
        k_weighted, sr,
        block_ms=MOMENTARY_BLOCK_MS,
        overlap=OVERLAP_FRACTION,
    )

    # Compute short-term loudness (3s blocks)
    short_term = compute_block_loudness(
        k_weighted, sr,
        block_ms=SHORT_TERM_BLOCK_MS,
        overlap=OVERLAP_FRACTION,
    )

    # Compute gated integrated loudness
    integrated = compute_gated_loudness(momentary)

    # Compute ungated loudness (for reference)
    valid_momentary = momentary[momentary > ABSOLUTE_GATE_LUFS]
    if len(valid_momentary) > 0:
        linear_vals = 10.0 ** ((valid_momentary - LUFS_OFFSET) / 10.0)
        ungated = LUFS_OFFSET + 10.0 * np.log10(np.mean(linear_vals))
    else:
        ungated = -np.inf

    # Sample peak
    sample_peak = measure_sample_peak(audio)

    # True peak (optional, slower)
    if compute_true_peak:
        true_peak = measure_true_peak(audio, sr)
    else:
        true_peak = sample_peak

    # Loudness range
    lra = compute_loudness_range(short_term)

    # Target gain calculation
    if integrated > -np.inf and not np.isinf(integrated):
        target_gain = target_lufs - integrated
    else:
        target_gain = 0.0

    # Short-term statistics
    valid_short_term = short_term[short_term > ABSOLUTE_GATE_LUFS]
    max_st = float(np.max(valid_short_term)) if len(valid_short_term) > 0 else -np.inf
    min_st = float(np.min(valid_short_term)) if len(valid_short_term) > 0 else np.inf

    # Clean up to free memory (512MB container limit)
    del k_weighted, audio
    gc.collect()

    profile = LoudnessProfile(
        integrated_lufs=float(integrated),
        short_term_lufs=short_term[short_term > -np.inf].tolist(),
        momentary_lufs=momentary[momentary > -np.inf].tolist(),
        true_peak_dbtp=float(true_peak),
        loudness_range_lu=float(lra),
        sample_peak_db=float(sample_peak),
        duration_seconds=float(duration),
        target_gain_db=float(target_gain),
        target_lufs=float(target_lufs),
        max_short_term_lufs=max_st,
        min_short_term_lufs=min_st,
        ungated_lufs=float(ungated),
    )

    logger.info(
        f"Loudness: {profile.integrated_lufs:.1f} LUFS, "
        f"Peak: {profile.true_peak_dbtp:.1f} dBTP, "
        f"LRA: {profile.loudness_range_lu:.1f} LU, "
        f"Gain needed: {profile.target_gain_db:+.1f} dB"
    )

    return profile


# ============================================================================
# LOUDNESS NORMALIZATION
# ============================================================================

def compute_normalization_gain(
    current_lufs: float,
    target_lufs: float = TARGET_LUFS_STREAMING,
    true_peak_dbtp: float = 0.0,
    max_true_peak_dbtp: float = -1.0,
) -> float:
    """
    Compute gain for loudness normalization with true peak limiting.

    Calculates the gain needed to reach target LUFS, but limits
    gain to prevent true peak from exceeding the ceiling.

    Args:
        current_lufs: Current integrated loudness in LUFS
        target_lufs: Desired loudness in LUFS
        true_peak_dbtp: Current true peak in dBTP
        max_true_peak_dbtp: Maximum allowed true peak (-1.0 dBTP standard)

    Returns:
        Gain in dB to apply
    """
    if np.isinf(current_lufs) or np.isnan(current_lufs):
        return 0.0

    desired_gain = target_lufs - current_lufs

    # Limit gain so true peak doesn't exceed ceiling
    headroom = max_true_peak_dbtp - true_peak_dbtp
    actual_gain = min(desired_gain, headroom)

    logger.debug(
        f"Normalization: desired={desired_gain:+.1f}dB, "
        f"headroom={headroom:+.1f}dB, actual={actual_gain:+.1f}dB"
    )

    return float(actual_gain)


def compute_gain_for_transition(
    profile_a: LoudnessProfile,
    profile_b: LoudnessProfile,
    target_lufs: float = TARGET_LUFS_DJ,
) -> Tuple[float, float]:
    """
    Compute per-track gains for a DJ transition.

    Matches loudness between two tracks for smooth transitions.

    Args:
        profile_a: Outgoing track loudness profile
        profile_b: Incoming track loudness profile
        target_lufs: Target loudness for both tracks

    Returns:
        Tuple of (gain_a_db, gain_b_db) to apply to each track
    """
    gain_a = compute_normalization_gain(
        profile_a.integrated_lufs, target_lufs,
        profile_a.true_peak_dbtp,
    )
    gain_b = compute_normalization_gain(
        profile_b.integrated_lufs, target_lufs,
        profile_b.true_peak_dbtp,
    )
    return gain_a, gain_b


# ============================================================================
# BATCH & EXPORT
# ============================================================================

def analyze_loudness_batch(
    filepaths: List[str],
    target_lufs: float = TARGET_LUFS_STREAMING,
) -> List[LoudnessProfile]:
    """
    Analyze loudness for multiple tracks sequentially.

    Per SPEC.md: one file at a time, explicit memory cleanup.

    Args:
        filepaths: List of audio file paths
        target_lufs: Target LUFS for gain calculation

    Returns:
        List of LoudnessProfile objects
    """
    profiles = []

    for i, fp in enumerate(filepaths):
        logger.info(f"Batch loudness [{i+1}/{len(filepaths)}]: {fp}")
        try:
            profile = analyze_loudness(fp, target_lufs=target_lufs)
            profiles.append(profile)
        except Exception as e:
            logger.warning(f"Failed to analyze {fp}: {e}")
            profiles.append(LoudnessProfile(
                integrated_lufs=-np.inf,
                duration_seconds=0.0,
            ))
        gc.collect()

    return profiles


def export_loudness_json(
    profiles: List[LoudnessProfile],
    filepaths: List[str],
    output_path: str,
) -> None:
    """
    Export loudness analysis results to JSON.

    Args:
        profiles: List of LoudnessProfile objects
        filepaths: Corresponding file paths
        output_path: Output JSON file path
    """
    output = {
        "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
        "phase": 4,
        "phase_name": "Loudness Analysis (ITU-R BS.1770-4)",
        "track_count": len(profiles),
        "target_lufs": profiles[0].target_lufs if profiles else TARGET_LUFS_STREAMING,
        "tracks": [
            {
                "file": fp,
                **profile.to_dict(),
            }
            for fp, profile in zip(filepaths, profiles)
        ],
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Loudness analysis exported to {output_path}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Phase 4 Loudness Analysis Module (ITU-R BS.1770-4)")
    print("Usage: analyze_loudness(filepath) -> LoudnessProfile")
    print(f"Target LUFS: {TARGET_LUFS_STREAMING} (streaming)")
