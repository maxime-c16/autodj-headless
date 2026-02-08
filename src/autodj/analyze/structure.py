"""
Track Structure Analysis Module
================================

Detects section boundaries, classifies sections (intro/drop/breakdown/outro),
generates semantic cue points and loop regions for Rekordbox-quality metadata.

Uses self-similarity matrix with checkerboard kernel novelty detection
(Foote 2000, McFee & Ellis 2014), optimized for electronic/techno music.

All algorithms use numpy/scipy only (no librosa dependency).

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import gc
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

import numpy as np
import scipy.signal as signal

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

SAMPLE_RATE = 44100
HOP_LENGTH = 512
N_FFT = 2048
N_MELS = 64                    # Mel bands for spectrogram
MIN_SECTION_BARS = 8           # Minimum section length in bars
CHECKERBOARD_SIZE = 64         # Kernel size for novelty detection
KICK_FREQ_LOW = 40.0           # Hz
KICK_FREQ_HIGH = 100.0         # Hz
BASS_FREQ_HIGH = 200.0         # Hz

# Section classification thresholds (techno-optimized)
INTRO_ENERGY_MAX = 0.4
DROP_ENERGY_MIN = 0.7
BREAKDOWN_ENERGY_MAX = 0.5
BUILDUP_SLOPE_MIN = 0.02


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Section:
    """A detected section of a track."""
    label: str               # "intro", "drop", "breakdown", "buildup", "outro"
    start_seconds: float
    end_seconds: float
    start_bar: int            # Bar number (from downbeat)
    end_bar: int
    energy: float             # 0.0-1.0 average energy in this section
    has_kick: bool            # True if 4-on-the-floor kick present
    confidence: float         # Detection confidence 0.0-1.0


@dataclass
class SemanticCue:
    """A DJ-meaningful labeled cue point."""
    label: str               # "mix_in", "drop_1", "breakdown_1", "drop_2", "mix_out"
    position_seconds: float
    position_bar: int
    type: str                # "hot_cue", "memory_cue", "loop_in", "loop_out"


@dataclass
class LoopRegion:
    """A detected loopable region."""
    start_seconds: float
    end_seconds: float
    length_bars: int          # 4, 8, 16, or 32
    energy: float             # Energy level 0.0-1.0
    stability: float          # Repetition stability score 0.0-1.0
    label: str                # "drop_loop", "breakdown_loop", "intro_loop"


@dataclass
class TrackStructure:
    """Complete structural analysis of a track."""
    sections: List[Section] = field(default_factory=list)
    cue_points: List[SemanticCue] = field(default_factory=list)
    loop_regions: List[LoopRegion] = field(default_factory=list)
    downbeat_position: float = 0.0       # Seconds to first downbeat
    bars_per_phrase: int = 8             # Usually 8 for techno
    total_bars: int = 0
    kick_pattern: str = "none"           # "four_on_floor", "breakbeat", "minimal", "none"
    has_vocal: bool = False              # True if vocal content detected


# ============================================================================
# MEL FILTERBANK
# ============================================================================

def _hz_to_mel(hz: float) -> float:
    """Convert frequency in Hz to mel scale."""
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    """Convert mel scale to frequency in Hz."""
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _create_mel_filterbank(
    n_mels: int, n_fft: int, sr: int, fmin: float = 0.0, fmax: float = None,
) -> np.ndarray:
    """Create a mel filterbank matrix.

    Args:
        n_mels: Number of mel bands
        n_fft: FFT size
        sr: Sample rate
        fmin: Minimum frequency
        fmax: Maximum frequency (defaults to sr/2)

    Returns:
        Filterbank matrix of shape (n_mels, n_fft//2 + 1)
    """
    if fmax is None:
        fmax = sr / 2.0

    n_freqs = n_fft // 2 + 1
    mel_min = _hz_to_mel(fmin)
    mel_max = _hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = np.array([_mel_to_hz(m) for m in mel_points])
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    filterbank = np.zeros((n_mels, n_freqs))
    for i in range(n_mels):
        left = bin_points[i]
        center = bin_points[i + 1]
        right = bin_points[i + 2]

        # Rising slope
        for j in range(left, center):
            if j < n_freqs and center > left:
                filterbank[i, j] = (j - left) / (center - left)
        # Falling slope
        for j in range(center, right):
            if j < n_freqs and right > center:
                filterbank[i, j] = (right - j) / (right - center)

    return filterbank


# ============================================================================
# CORE ALGORITHMS
# ============================================================================

def _compute_mel_spectrogram(
    audio: np.ndarray, sr: int, n_mels: int = N_MELS,
    n_fft: int = N_FFT, hop: int = HOP_LENGTH,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute mel-frequency spectrogram.

    Args:
        audio: Audio signal (1D float32)
        sr: Sample rate
        n_mels: Number of mel bands
        n_fft: FFT window size
        hop: Hop length

    Returns:
        Tuple of (mel_spec [n_mels x n_frames], time_axis [n_frames])
    """
    # Compute STFT
    f, t, Zxx = signal.stft(audio, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    power = np.abs(Zxx) ** 2

    # Apply mel filterbank
    mel_fb = _create_mel_filterbank(n_mels, n_fft, sr)
    mel_spec = mel_fb @ power

    # Log scaling (add small epsilon to avoid log(0))
    mel_spec = np.log1p(mel_spec * 1000.0)

    return mel_spec, t


def _compute_self_similarity(mel_spec: np.ndarray) -> np.ndarray:
    """Compute self-similarity matrix using cosine similarity.

    For memory efficiency on long tracks (>10 min), downsample frames by 2x.

    Args:
        mel_spec: Mel spectrogram [n_mels x n_frames]

    Returns:
        Self-similarity matrix [n_frames x n_frames]
    """
    n_frames = mel_spec.shape[1]

    # Downsample for long tracks to keep memory under control
    # 5000 frames at 44100/512 hop = ~58 seconds per frame, 5000 frames = ~5 min
    # For a 7-min track at hop=512: ~600 frames. For 20-min: ~1900 frames.
    # SSM of 5000x5000 float32 = 100MB, so cap at 5000.
    step = 1
    if n_frames > 5000:
        step = (n_frames // 5000) + 1

    spec = mel_spec[:, ::step]
    n = spec.shape[1]

    # L2 normalize columns
    norms = np.linalg.norm(spec, axis=0, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    spec_norm = spec / norms

    # Cosine similarity
    ssm = spec_norm.T @ spec_norm

    return ssm


def _checkerboard_kernel(size: int) -> np.ndarray:
    """Create a checkerboard kernel for novelty detection (Foote 2000).

    Args:
        size: Kernel size (should be even)

    Returns:
        Checkerboard kernel of shape (size, size)
    """
    half = size // 2
    kernel = np.ones((size, size))
    # Off-diagonal blocks = -1 (cross-boundary, low similarity)
    # Diagonal blocks = +1 (same-section, high similarity)
    # At a boundary: +1*high + -1*low + -1*low + +1*high > 0
    kernel[:half, half:] = -1.0
    kernel[half:, :half] = -1.0
    return kernel


def _compute_novelty_curve(ssm: np.ndarray, kernel_size: int = CHECKERBOARD_SIZE) -> np.ndarray:
    """Compute novelty curve from self-similarity matrix using checkerboard kernel.

    Args:
        ssm: Self-similarity matrix
        kernel_size: Checkerboard kernel size

    Returns:
        Novelty curve (1D array, same length as ssm diagonal)
    """
    n = ssm.shape[0]
    # Ensure kernel fits
    ks = min(kernel_size, n // 2)
    if ks < 4:
        return np.zeros(n)

    # Make it even
    ks = ks - (ks % 2)

    kernel = _checkerboard_kernel(ks)
    half = ks // 2

    novelty = np.zeros(n)
    for i in range(half, n - half):
        patch = ssm[i - half:i + half, i - half:i + half]
        if patch.shape == kernel.shape:
            novelty[i] = np.sum(patch * kernel)

    # Rectify (only positive novelty = boundaries)
    novelty = np.maximum(novelty, 0.0)

    # Normalize
    nmax = np.max(novelty)
    if nmax > 0:
        novelty = novelty / nmax

    return novelty


def _snap_to_bar(seconds: float, bpm: float, downbeat: float) -> int:
    """Snap a time position to the nearest bar boundary.

    Args:
        seconds: Time in seconds
        bpm: Beats per minute
        downbeat: Downbeat position in seconds

    Returns:
        Bar number (0-based)
    """
    if bpm <= 0:
        return 0
    seconds_per_bar = 4 * 60.0 / bpm  # 4 beats per bar
    bar = round((seconds - downbeat) / seconds_per_bar)
    return max(0, bar)


def _bar_to_seconds(bar: int, bpm: float, downbeat: float) -> float:
    """Convert bar number to seconds.

    Args:
        bar: Bar number (0-based)
        bpm: Beats per minute
        downbeat: Downbeat position in seconds

    Returns:
        Time in seconds
    """
    if bpm <= 0:
        return downbeat
    seconds_per_bar = 4 * 60.0 / bpm
    return downbeat + bar * seconds_per_bar


def _compute_rms_energy(audio: np.ndarray, sr: int, hop: int = HOP_LENGTH) -> np.ndarray:
    """Compute RMS energy per frame.

    Args:
        audio: Audio signal
        sr: Sample rate
        hop: Hop length in samples

    Returns:
        Normalized RMS energy (0.0-1.0) per frame
    """
    n_frames = len(audio) // hop
    energy = np.zeros(n_frames)

    for i in range(n_frames):
        start = i * hop
        end = min(start + hop * 2, len(audio))  # Use 2x hop for smoother energy
        frame = audio[start:end]
        energy[i] = np.sqrt(np.mean(frame ** 2))

    emax = np.max(energy)
    if emax > 0:
        energy = energy / emax
    return energy


def _compute_bass_energy(audio: np.ndarray, sr: int, hop: int = HOP_LENGTH) -> np.ndarray:
    """Compute bass energy (20-200Hz) per frame using bandpass filter.

    Args:
        audio: Audio signal
        sr: Sample rate
        hop: Hop length

    Returns:
        Normalized bass energy per frame
    """
    # Bandpass filter for bass (20-200Hz)
    nyquist = sr / 2.0
    low = max(20.0 / nyquist, 0.001)
    high = min(BASS_FREQ_HIGH / nyquist, 0.999)

    if low >= high:
        return np.zeros(len(audio) // hop)

    try:
        sos = signal.butter(4, [low, high], btype='band', output='sos')
        bass_audio = signal.sosfilt(sos, audio)
    except Exception:
        return np.zeros(len(audio) // hop)

    return _compute_rms_energy(bass_audio, sr, hop)


def _compute_kick_energy(audio: np.ndarray, sr: int, hop: int = HOP_LENGTH) -> np.ndarray:
    """Compute kick drum energy (40-100Hz) per frame.

    Args:
        audio: Audio signal
        sr: Sample rate
        hop: Hop length

    Returns:
        Normalized kick energy per frame
    """
    nyquist = sr / 2.0
    low = max(KICK_FREQ_LOW / nyquist, 0.001)
    high = min(KICK_FREQ_HIGH / nyquist, 0.999)

    if low >= high:
        return np.zeros(len(audio) // hop)

    try:
        sos = signal.butter(4, [low, high], btype='band', output='sos')
        kick_audio = signal.sosfilt(sos, audio)
    except Exception:
        return np.zeros(len(audio) // hop)

    return _compute_rms_energy(kick_audio, sr, hop)


# ============================================================================
# PUBLIC FUNCTIONS
# ============================================================================

def detect_downbeat(audio: np.ndarray, sr: int, bpm: float) -> float:
    """Detect the first downbeat (bar 1, beat 1) position.

    Uses onset strength and beat period alignment to find bar boundaries.
    Groups beats into bars (4 beats) and identifies strongest onset cluster.

    Args:
        audio: Audio signal (mono float32)
        sr: Sample rate
        bpm: Detected BPM

    Returns:
        Downbeat position in seconds
    """
    if bpm <= 0:
        return 0.0

    beat_period = 60.0 / bpm  # seconds per beat
    bar_period = beat_period * 4  # seconds per bar

    # Compute onset strength envelope
    hop = HOP_LENGTH
    energy = _compute_rms_energy(audio, sr, hop)

    # Find onset peaks
    peaks, props = signal.find_peaks(
        energy, height=0.3, distance=int(beat_period * sr / hop * 0.5)
    )

    if len(peaks) == 0:
        # Fallback: find first significant energy
        for i, e in enumerate(energy):
            if e > 0.1:
                return i * hop / sr
        return 0.0

    # Find the first strong onset cluster
    # Look at early peaks (first 20 seconds)
    max_frames = int(20.0 * sr / hop)
    early_peaks = peaks[peaks < max_frames]

    if len(early_peaks) == 0:
        early_peaks = peaks[:4]

    # The first strong peak is our best downbeat estimate
    if len(early_peaks) > 0:
        # Find highest energy among early peaks
        peak_energies = energy[early_peaks]
        best_idx = early_peaks[np.argmax(peak_energies)]
        downbeat = best_idx * hop / sr

        # Snap to nearest bar boundary from start
        bar_offset = downbeat % bar_period
        if bar_offset > bar_period / 2:
            downbeat = downbeat - bar_offset + bar_period
        else:
            downbeat = downbeat - bar_offset

        return max(0.0, downbeat)

    return 0.0


def detect_sections(
    audio: np.ndarray, sr: int, bpm: float,
    downbeat: Optional[float] = None,
) -> List[Section]:
    """Detect section boundaries using self-similarity and novelty.

    Algorithm:
    1. Compute mel spectrogram (64 bands)
    2. Build self-similarity matrix (cosine similarity)
    3. Apply checkerboard kernel for novelty (Foote 2000)
    4. Peak-pick novelty curve -> section boundaries
    5. Snap boundaries to nearest bar

    Args:
        audio: Audio signal (mono float32)
        sr: Sample rate
        bpm: Detected BPM
        downbeat: Downbeat position in seconds (auto-detected if None)

    Returns:
        List of Section objects (unlabeled, energy computed)
    """
    if downbeat is None:
        downbeat = detect_downbeat(audio, sr, bpm)

    duration = len(audio) / sr

    if bpm <= 0:
        # Can't do bar-aligned analysis without BPM
        return [Section(
            label="unknown",
            start_seconds=0.0, end_seconds=duration,
            start_bar=0, end_bar=0,
            energy=0.5, has_kick=False, confidence=0.0,
        )]

    seconds_per_bar = 4 * 60.0 / bpm
    min_section_seconds = MIN_SECTION_BARS * seconds_per_bar

    # Compute mel spectrogram
    mel_spec, time_axis = _compute_mel_spectrogram(audio, sr)

    # Compute self-similarity matrix
    ssm = _compute_self_similarity(mel_spec)

    # Compute novelty curve
    novelty = _compute_novelty_curve(ssm)

    # Map novelty back to original time scale (if downsampled in SSM)
    n_orig_frames = mel_spec.shape[1]
    if len(novelty) < n_orig_frames:
        # Interpolate novelty back to original frame rate
        novelty = np.interp(
            np.linspace(0, len(novelty) - 1, n_orig_frames),
            np.arange(len(novelty)),
            novelty,
        )

    # Free SSM memory
    del ssm
    gc.collect()

    # Peak-pick novelty curve (minimum distance = min_section_seconds)
    min_dist_frames = max(1, int(min_section_seconds * sr / HOP_LENGTH))
    peaks, props = signal.find_peaks(
        novelty, height=0.15, distance=min_dist_frames,
    )

    # Convert frame indices to seconds
    if len(time_axis) > 0:
        frame_to_sec = time_axis[-1] / (len(time_axis) - 1) if len(time_axis) > 1 else HOP_LENGTH / sr
    else:
        frame_to_sec = HOP_LENGTH / sr

    boundary_seconds = [0.0]
    for p in peaks:
        if p < len(time_axis):
            t = time_axis[p]
        else:
            t = p * frame_to_sec
        # Snap to bar boundary
        bar = _snap_to_bar(t, bpm, downbeat)
        t_snapped = _bar_to_seconds(bar, bpm, downbeat)
        if t_snapped > 0 and t_snapped < duration - min_section_seconds:
            boundary_seconds.append(t_snapped)
    boundary_seconds.append(duration)

    # Remove duplicates and sort
    boundary_seconds = sorted(set(boundary_seconds))

    # Remove sections shorter than minimum
    filtered = [boundary_seconds[0]]
    for b in boundary_seconds[1:]:
        if b - filtered[-1] >= min_section_seconds * 0.5:
            filtered.append(b)
    if filtered[-1] < duration:
        filtered.append(duration)
    boundary_seconds = filtered

    # Compute per-section features
    rms_energy = _compute_rms_energy(audio, sr)
    kick_energy = _compute_kick_energy(audio, sr)

    sections = []
    for i in range(len(boundary_seconds) - 1):
        start_sec = boundary_seconds[i]
        end_sec = boundary_seconds[i + 1]

        start_bar = _snap_to_bar(start_sec, bpm, downbeat)
        end_bar = _snap_to_bar(end_sec, bpm, downbeat)

        # Compute average energy for this section
        start_frame = int(start_sec * sr / HOP_LENGTH)
        end_frame = int(end_sec * sr / HOP_LENGTH)
        start_frame = max(0, min(start_frame, len(rms_energy) - 1))
        end_frame = max(start_frame + 1, min(end_frame, len(rms_energy)))

        section_energy = np.mean(rms_energy[start_frame:end_frame])

        # Check kick presence
        section_kick = np.mean(kick_energy[start_frame:end_frame])
        has_kick = bool(section_kick > 0.15)

        # Confidence based on novelty peak strength
        confidence = 0.5  # default
        if i < len(peaks) and i > 0:
            conf_idx = peaks[i - 1] if i - 1 < len(peaks) else 0
            if conf_idx < len(novelty):
                confidence = min(1.0, novelty[conf_idx])

        sections.append(Section(
            label="unknown",
            start_seconds=round(start_sec, 3),
            end_seconds=round(end_sec, 3),
            start_bar=start_bar,
            end_bar=end_bar,
            energy=round(float(section_energy), 4),
            has_kick=has_kick,
            confidence=round(float(confidence), 4),
        ))

    if not sections:
        total_bars = max(1, int(duration / seconds_per_bar))
        sections = [Section(
            label="unknown",
            start_seconds=0.0, end_seconds=duration,
            start_bar=0, end_bar=total_bars,
            energy=float(np.mean(rms_energy)) if len(rms_energy) > 0 else 0.5,
            has_kick=False, confidence=0.0,
        )]

    return sections


def classify_sections(
    sections: List[Section], audio: np.ndarray, sr: int, bpm: float,
) -> List[Section]:
    """Classify sections with labels based on energy and kick patterns.

    Classification rules (techno-optimized):
    - intro: first section, energy < 0.4 OR no kick
    - drop: energy > 0.7 AND has_kick AND follows buildup/breakdown
    - breakdown: energy < 0.5 AND no kick (kick drops out)
    - buildup: energy rising, precedes drop
    - outro: last section, energy < 0.4 OR energy declining

    Args:
        sections: List of sections with energy/kick computed
        audio: Audio signal (for additional analysis if needed)
        sr: Sample rate
        bpm: BPM

    Returns:
        Same sections list with labels assigned
    """
    if not sections:
        return sections

    n = len(sections)

    # Single section: label based on energy
    if n == 1:
        if sections[0].energy > DROP_ENERGY_MIN and sections[0].has_kick:
            sections[0].label = "drop"
        else:
            sections[0].label = "intro"
        return sections

    # Multi-section classification
    for i, sec in enumerate(sections):
        is_first = (i == 0)
        is_last = (i == n - 1)

        # Energy of previous/next sections for context
        prev_energy = sections[i - 1].energy if i > 0 else 0.0
        next_energy = sections[i + 1].energy if i < n - 1 else 0.0

        # Intro: first section, low energy or no kick
        if is_first and (sec.energy < INTRO_ENERGY_MAX or not sec.has_kick):
            sec.label = "intro"
            continue

        # Outro: last section, low energy or declining energy
        if is_last and (sec.energy < INTRO_ENERGY_MAX or sec.energy < prev_energy):
            sec.label = "outro"
            continue

        # Drop: high energy with kick, follows lower energy
        if sec.energy >= DROP_ENERGY_MIN and sec.has_kick and prev_energy < sec.energy:
            sec.label = "drop"
            continue

        # Breakdown: low energy, no kick
        if sec.energy < BREAKDOWN_ENERGY_MAX and not sec.has_kick:
            sec.label = "breakdown"
            continue

        # Buildup: energy rising, next section is higher energy
        if next_energy > sec.energy and sec.energy > prev_energy:
            sec.label = "buildup"
            continue

        # Default: if high energy with kick, it's a drop
        if sec.energy >= DROP_ENERGY_MIN and sec.has_kick:
            sec.label = "drop"
        elif sec.has_kick:
            sec.label = "drop"
        else:
            sec.label = "breakdown"

    return sections


def analyze_kick_pattern(
    audio: np.ndarray, sr: int, bpm: float,
    sections: Optional[List[Section]] = None,
) -> str:
    """Analyze overall kick pattern of the track.

    For each section, band-pass filter 40-100Hz (kick fundamental),
    compute autocorrelation at beat period.

    Args:
        audio: Audio signal
        sr: Sample rate
        bpm: BPM
        sections: Optional sections (for per-section analysis)

    Returns:
        Pattern string: "four_on_floor", "breakbeat", "minimal", "none"
    """
    if bpm <= 0:
        return "none"

    kick_energy = _compute_kick_energy(audio, sr)

    if len(kick_energy) == 0:
        return "none"

    mean_kick = float(np.mean(kick_energy))

    if mean_kick < 0.05:
        return "none"

    # Compute autocorrelation at beat period
    beat_period_frames = int(60.0 / bpm * sr / HOP_LENGTH)
    if beat_period_frames >= len(kick_energy) // 2:
        if mean_kick > 0.15:
            return "minimal"
        return "none"

    # Full autocorrelation and check periodicity at beat period
    n = len(kick_energy)
    # Normalize energy for autocorrelation
    kick_centered = kick_energy - np.mean(kick_energy)
    variance = np.sum(kick_centered ** 2)
    if variance < 1e-10:
        return "none"

    # Check autocorrelation at the beat period lag
    lag = beat_period_frames
    if lag < n:
        autocorr_at_beat = float(np.sum(kick_centered[:n - lag] * kick_centered[lag:])) / variance
    else:
        autocorr_at_beat = 0.0

    # Strong regular kicks = four on the floor
    # High autocorrelation at beat period means regular kick pattern
    if mean_kick > 0.1 and autocorr_at_beat > 0.3:
        return "four_on_floor"
    elif mean_kick > 0.08:
        return "minimal"
    else:
        return "none"


def generate_semantic_cues(
    sections: List[Section], bpm: float, duration: float,
) -> List[SemanticCue]:
    """Generate DJ-meaningful labeled cue points from section boundaries.

    Cue points generated:
    - mix_in: start of first drop (or end of intro)
    - drop_1: start of first drop section
    - breakdown_1: start of first breakdown
    - drop_2: start of second drop (if exists)
    - mix_out: start of outro section
    - last_32: 32 bars before track end

    Args:
        sections: Classified sections
        bpm: BPM
        duration: Track duration in seconds

    Returns:
        List of SemanticCue objects
    """
    cues = []

    # Find sections by type
    drops = [s for s in sections if s.label == "drop"]
    breakdowns = [s for s in sections if s.label == "breakdown"]
    intros = [s for s in sections if s.label == "intro"]
    outros = [s for s in sections if s.label == "outro"]

    # mix_in: end of intro, or start of first drop
    if intros:
        mix_in_sec = intros[0].end_seconds
        mix_in_bar = intros[0].end_bar
    elif drops:
        mix_in_sec = drops[0].start_seconds
        mix_in_bar = drops[0].start_bar
    else:
        # Fallback: 10% into the track
        mix_in_sec = duration * 0.1
        mix_in_bar = _snap_to_bar(mix_in_sec, bpm, 0.0)

    cues.append(SemanticCue(
        label="mix_in",
        position_seconds=round(mix_in_sec, 3),
        position_bar=mix_in_bar,
        type="hot_cue",
    ))

    # drop_1
    if len(drops) >= 1:
        cues.append(SemanticCue(
            label="drop_1",
            position_seconds=round(drops[0].start_seconds, 3),
            position_bar=drops[0].start_bar,
            type="hot_cue",
        ))

    # breakdown_1
    if len(breakdowns) >= 1:
        cues.append(SemanticCue(
            label="breakdown_1",
            position_seconds=round(breakdowns[0].start_seconds, 3),
            position_bar=breakdowns[0].start_bar,
            type="memory_cue",
        ))

    # drop_2
    if len(drops) >= 2:
        cues.append(SemanticCue(
            label="drop_2",
            position_seconds=round(drops[1].start_seconds, 3),
            position_bar=drops[1].start_bar,
            type="hot_cue",
        ))

    # mix_out: start of outro
    if outros:
        cues.append(SemanticCue(
            label="mix_out",
            position_seconds=round(outros[0].start_seconds, 3),
            position_bar=outros[0].start_bar,
            type="hot_cue",
        ))
    else:
        # Fallback: 85% into the track
        mix_out_sec = duration * 0.85
        mix_out_bar = _snap_to_bar(mix_out_sec, bpm, 0.0) if bpm > 0 else 0
        cues.append(SemanticCue(
            label="mix_out",
            position_seconds=round(mix_out_sec, 3),
            position_bar=mix_out_bar,
            type="hot_cue",
        ))

    # last_32: 32 bars before end
    if bpm > 0:
        last_32_sec = max(0.0, duration - 32 * 4 * 60.0 / bpm)
        last_32_bar = _snap_to_bar(last_32_sec, bpm, 0.0)
        cues.append(SemanticCue(
            label="last_32",
            position_seconds=round(last_32_sec, 3),
            position_bar=last_32_bar,
            type="memory_cue",
        ))

    return cues


def detect_loop_regions(
    sections: List[Section], audio: np.ndarray, sr: int, bpm: float,
) -> List[LoopRegion]:
    """Detect loopable regions based on section stability and energy.

    For each section, measures repetition stability by computing
    self-similarity within the section and finding repeating sub-patterns.

    Args:
        sections: Classified sections
        audio: Audio signal
        sr: Sample rate
        bpm: BPM

    Returns:
        List of LoopRegion objects
    """
    if bpm <= 0:
        return []

    loops = []
    seconds_per_bar = 4 * 60.0 / bpm

    for sec in sections:
        sec_duration = sec.end_seconds - sec.start_seconds
        sec_bars = sec.end_bar - sec.start_bar

        if sec_bars < 4:
            continue

        # Determine loop length based on section type
        if sec.label == "drop":
            loop_bars = min(16, sec_bars)
            label = "drop_loop"
        elif sec.label == "breakdown":
            loop_bars = min(8, sec_bars)
            label = "breakdown_loop"
        elif sec.label == "intro":
            loop_bars = min(8, sec_bars)
            label = "intro_loop"
        else:
            loop_bars = min(8, sec_bars)
            label = f"{sec.label}_loop"

        # Ensure loop_bars is a power of 2 (4, 8, 16, 32)
        for target in [32, 16, 8, 4]:
            if loop_bars >= target:
                loop_bars = target
                break

        loop_duration = loop_bars * seconds_per_bar
        if loop_duration <= 0 or loop_duration > sec_duration:
            continue

        # Compute stability score using section audio
        start_sample = int(sec.start_seconds * sr)
        end_sample = int(sec.end_seconds * sr)
        start_sample = max(0, min(start_sample, len(audio) - 1))
        end_sample = max(start_sample + 1, min(end_sample, len(audio)))

        section_audio = audio[start_sample:end_sample]

        # Stability: autocorrelation at loop period
        loop_samples = int(loop_duration * sr)
        if loop_samples >= len(section_audio):
            stability = 0.3
        else:
            # Compare first loop to second loop
            first_loop = section_audio[:loop_samples]
            second_start = loop_samples
            second_end = min(second_start + loop_samples, len(section_audio))
            second_loop = section_audio[second_start:second_end]

            # Pad to same length
            min_len = min(len(first_loop), len(second_loop))
            if min_len > 0:
                corr = np.corrcoef(
                    first_loop[:min_len],
                    second_loop[:min_len],
                )[0, 1]
                stability = max(0.0, float(corr)) if not np.isnan(corr) else 0.3
            else:
                stability = 0.3

        loops.append(LoopRegion(
            start_seconds=round(sec.start_seconds, 3),
            end_seconds=round(sec.start_seconds + loop_duration, 3),
            length_bars=loop_bars,
            energy=sec.energy,
            stability=round(stability, 4),
            label=label,
        ))

    return loops


def detect_vocal(audio: np.ndarray, sr: int) -> bool:
    """Simple vocal detection based on mid-frequency spectral flatness.

    Vocal content tends to have lower spectral flatness (more tonal)
    in the 300Hz-4kHz range compared to pure instrumental.

    Args:
        audio: Audio signal
        sr: Sample rate

    Returns:
        True if vocal content likely present
    """
    # Bandpass 300Hz-4kHz (vocal fundamental + harmonics)
    nyquist = sr / 2.0
    low = 300.0 / nyquist
    high = min(4000.0 / nyquist, 0.999)

    if low >= high:
        return False

    try:
        sos = signal.butter(4, [low, high], btype='band', output='sos')
        vocal_band = signal.sosfilt(sos, audio)
    except Exception:
        return False

    # Compute spectral flatness (geometric mean / arithmetic mean)
    # Low flatness = tonal = likely vocal
    n_fft = 2048
    hop = 512
    n_frames = max(1, len(vocal_band) // hop - 1)

    flatness_values = []
    for i in range(min(n_frames, 100)):  # Sample first 100 frames
        start = i * hop
        end = start + n_fft
        if end > len(vocal_band):
            break
        frame = vocal_band[start:end] * np.hanning(n_fft)
        spectrum = np.abs(np.fft.rfft(frame))
        spectrum = spectrum + 1e-10

        geo_mean = np.exp(np.mean(np.log(spectrum)))
        arith_mean = np.mean(spectrum)
        flatness = geo_mean / arith_mean if arith_mean > 0 else 1.0
        flatness_values.append(flatness)

    if not flatness_values:
        return False

    avg_flatness = float(np.mean(flatness_values))
    # Low flatness (<0.15) indicates strongly tonal content (possible vocals)
    # Noise has flatness ~0.3-0.5, pure tones ~0.01-0.05
    return avg_flatness < 0.15


def analyze_track_structure(
    audio: np.ndarray, sr: int, bpm: float,
) -> TrackStructure:
    """Complete structural analysis of a track.

    Orchestrator that calls all analysis functions and combines results.

    Args:
        audio: Audio signal (mono float32)
        sr: Sample rate
        bpm: Detected BPM

    Returns:
        TrackStructure with sections, cue points, loops, and metadata
    """
    duration = len(audio) / sr

    logger.info(f"Structure analysis: {duration:.1f}s, {bpm:.1f} BPM")

    # 1. Detect downbeat
    downbeat = detect_downbeat(audio, sr, bpm)
    logger.debug(f"Downbeat: {downbeat:.3f}s")

    # 2. Detect sections
    sections = detect_sections(audio, sr, bpm, downbeat=downbeat)
    logger.debug(f"Detected {len(sections)} sections")

    # 3. Classify sections
    sections = classify_sections(sections, audio, sr, bpm)
    labels = [s.label for s in sections]
    logger.debug(f"Section labels: {labels}")

    # 4. Analyze kick pattern
    kick_pattern = analyze_kick_pattern(audio, sr, bpm, sections)
    logger.debug(f"Kick pattern: {kick_pattern}")

    # 5. Generate semantic cues
    cue_points = generate_semantic_cues(sections, bpm, duration)
    logger.debug(f"Generated {len(cue_points)} cue points")

    # 6. Detect loop regions
    loop_regions = detect_loop_regions(sections, audio, sr, bpm)
    logger.debug(f"Detected {len(loop_regions)} loop regions")

    # 7. Detect vocals (sample only, to save memory)
    has_vocal = bool(detect_vocal(audio, sr))

    # 8. Compute total bars
    total_bars = 0
    if bpm > 0:
        seconds_per_bar = 4 * 60.0 / bpm
        total_bars = max(1, int(duration / seconds_per_bar))

    structure = TrackStructure(
        sections=sections,
        cue_points=cue_points,
        loop_regions=loop_regions,
        downbeat_position=round(downbeat, 3),
        bars_per_phrase=8,
        total_bars=total_bars,
        kick_pattern=kick_pattern,
        has_vocal=has_vocal,
    )

    logger.info(
        f"Structure complete: {len(sections)} sections, "
        f"{len(cue_points)} cues, {len(loop_regions)} loops, "
        f"kick={kick_pattern}, vocal={has_vocal}"
    )

    return structure
