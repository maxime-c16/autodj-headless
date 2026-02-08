"""
Phase 3: Spectral Analysis & Smart Cue Detection Module
========================================================

This module provides FFT-based audio analysis for detecting:
- Energy peaks (kicks, drops, buildups)
- Smart cue points (intro/outro, optimal mixing points)
- Frequency content analysis (bass, mids, treble, rumble)
- Intro/outro boundaries

Uses scipy.signal.stft for robust frequency analysis.

Author: Claude Opus DSP Implementation
Date: 2026-02-07
"""

import json
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

try:
    import scipy.io.wavfile as wavfile
    import scipy.signal as signal
except ImportError:
    raise ImportError("scipy required: pip install scipy")

from src.autodj.analyze.dsp_config import DSPConfig

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# ============================================================================
# CONSTANTS (defaults, used when no DSPConfig is provided)
# ============================================================================

# FFT parameters
SAMPLE_RATE = 44100  # Standard CD quality
HOP_LENGTH = 512     # Samples per frame (11.6ms at 44.1kHz)
N_FFT = 2048         # FFT window size
WINDOW = "hann"      # Hann window for FFT

# Frequency bands (Hz)
RUMBLE_FREQ_LOW = 0
RUMBLE_FREQ_HIGH = 20      # <20 Hz rumble/sub-bass
BASS_FREQ_LOW = 20
BASS_FREQ_HIGH = 200       # 20-200 Hz kick/bass
MID_FREQ_LOW = 200
MID_FREQ_HIGH = 2000       # 200Hz-2kHz mids
TREBLE_FREQ_LOW = 2000
TREBLE_FREQ_HIGH = 20000   # 2kHz-20kHz treble/brilliance

# Detection thresholds
ENERGY_THRESHOLD_DEFAULT = 0.7  # 0.0-1.0
KICK_THRESHOLD = 0.75           # For kick detection
QUIET_THRESHOLD = 0.05          # Energy below this = silence


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SmartCues:
    """Detected smart cue points in a track."""
    intro_end: Optional[float] = None        # Seconds where intro ends
    first_kick: Optional[float] = None       # First major kick/drop
    buildups: List[float] = None             # List of buildup timestamps
    drops: List[float] = None                # Sudden energy drops
    outro_start: Optional[float] = None      # Where outro begins
    outro_end: Optional[float] = None        # End of track
    
    def __post_init__(self):
        if self.buildups is None:
            self.buildups = []
        if self.drops is None:
            self.drops = []


@dataclass
class SpectralCharacteristics:
    """Frequency content analysis."""
    bass_energy: float       # 0.0-1.0, normalized (20-200Hz)
    mid_energy: float        # 0.0-1.0, normalized (200Hz-2kHz)
    treble_energy: float     # 0.0-1.0, normalized (2kHz-20kHz)
    rumble_presence: float   # 0.0-1.0, normalized (<20Hz)
    kick_detected: bool      # Whether track has strong kick
    bassline_present: bool   # Whether track has bass content


@dataclass
class EnergyProfile:
    """Energy analysis over time."""
    energy_timeline: np.ndarray      # Energy vs time (1D array)
    peaks: List[float]               # List of peak timestamps
    peak_strengths: List[float]      # Confidence scores (0.0-1.0)
    time_axis: np.ndarray            # Time in seconds for each frame


# ============================================================================
# AUDIO LOADING
# ============================================================================

def load_audio(file_path: str) -> Tuple[np.ndarray, int]:
    """
    Load audio file and return audio data and sample rate.
    
    Args:
        file_path: Path to audio file (.wav, .mp3, .m4a, etc.)
        
    Returns:
        Tuple of (audio_data, sample_rate)
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If audio format not supported
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")
    
    # Try different libraries based on file extension
    suffix = path.suffix.lower()
    
    try:
        if suffix == ".wav":
            sr, audio = wavfile.read(file_path)
            # Convert stereo to mono if needed
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
            return audio.astype(np.float32) / 32768.0, sr
        else:
            # For mp3, m4a, etc., try librosa
            try:
                import librosa
                audio, sr = librosa.load(file_path, sr=SAMPLE_RATE, mono=True)
                return audio.astype(np.float32), sr
            except ImportError:
                raise ValueError(
                    f"librosa required for {suffix} files. Install: pip install librosa"
                )
    except Exception as e:
        raise ValueError(f"Failed to load {file_path}: {e}")


# ============================================================================
# ENERGY ANALYSIS
# ============================================================================

def analyze_energy_profile(
    file_path: str,
    audio_data: Optional[Tuple[np.ndarray, int]] = None,
    config: Optional[DSPConfig] = None,
) -> EnergyProfile:
    """
    Analyze energy profile of an audio file using STFT.

    Args:
        file_path: Path to audio file
        audio_data: Optional pre-loaded (audio, sr) tuple from AudioCache
        config: Optional DSPConfig for parameters

    Returns:
        EnergyProfile with energy timeline, peaks, and strengths
    """
    logger.debug(f"Analyzing energy profile: {file_path}")

    n_fft = config.fft_size if config else N_FFT
    hop = config.hop_length if config else HOP_LENGTH
    threshold = config.energy_threshold if config else ENERGY_THRESHOLD_DEFAULT

    # Load audio (or use cached)
    if audio_data is not None:
        audio, sr = audio_data
    else:
        audio, sr = load_audio(file_path)

    # Compute STFT
    S = signal.stft(audio, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    freqs = S[0]
    times = S[1]
    Sxx = S[2]

    # Compute energy magnitude
    energy = np.sum(np.abs(Sxx), axis=0)

    # Normalize energy
    energy_max = np.max(energy)
    if energy_max > 0:
        energy = energy / energy_max

    # Find peaks
    peaks, properties = signal.find_peaks(
        energy,
        height=threshold,
        distance=int(sr / hop * 0.5)  # At least 0.5 sec apart
    )

    peak_times = times[peaks]
    peak_strengths = properties["peak_heights"].tolist()

    logger.debug(f"Found {len(peaks)} energy peaks")

    return EnergyProfile(
        energy_timeline=energy,
        peaks=peak_times.tolist(),
        peak_strengths=peak_strengths,
        time_axis=times
    )


def detect_energy_peaks(
    spectrum: np.ndarray,
    threshold: float = 0.7,
    min_distance: float = 0.5
) -> List[float]:
    """
    Detect high-energy regions (kicks, drops, buildups).
    
    Args:
        spectrum: 1D energy array
        threshold: Energy threshold (0.0-1.0)
        min_distance: Minimum seconds between peaks
        
    Returns:
        List of peak timestamps (seconds)
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"Threshold must be 0.0-1.0, got {threshold}")
    
    # Normalize spectrum
    spectrum_norm = spectrum / (np.max(spectrum) + 1e-10)
    
    # Find peaks
    peaks, _ = signal.find_peaks(
        spectrum_norm,
        height=threshold,
        distance=int(min_distance * 44100 / HOP_LENGTH)  # Convert to samples
    )
    
    return peaks.tolist()


# ============================================================================
# SMART CUE DETECTION
# ============================================================================

def identify_smart_cues(
    audio_file: str,
    audio_data: Optional[Tuple[np.ndarray, int]] = None,
    config: Optional[DSPConfig] = None,
) -> SmartCues:
    """
    Auto-detect optimal cue points in an audio file.

    Detects:
    - Intro end (where first kick/major energy appears)
    - First kick (major energy peak in first half)
    - Buildups (gradual energy increases)
    - Outro start (sustained low energy near end)
    - Outro end (file end)

    Args:
        audio_file: Path to audio file
        audio_data: Optional pre-loaded (audio, sr) tuple from AudioCache
        config: Optional DSPConfig for parameters

    Returns:
        SmartCues with detected cue points
    """
    logger.debug(f"Detecting smart cues: {audio_file}")

    hop = config.hop_length if config else HOP_LENGTH

    # Load and analyze (or use cached)
    if audio_data is not None:
        audio, sr = audio_data
    else:
        audio, sr = load_audio(audio_file)
    duration = len(audio) / sr

    # Compute energy profile (reuse same audio_data)
    profile = analyze_energy_profile(audio_file, audio_data=(audio, sr), config=config)
    energy = profile.energy_timeline
    times = profile.time_axis
    
    cues = SmartCues()
    
    # 1. Detect intro end (first significant energy peak)
    for i, e in enumerate(energy):
        if e > 0.3:  # Intro ends when energy rises
            cues.intro_end = times[i]
            break
    if cues.intro_end is None:
        cues.intro_end = min(32.0, duration * 0.1)  # Default: 32sec or 10%
    
    # 2. Detect first kick (major energy peak in first 45 seconds)
    intro_end_idx = int(cues.intro_end * sr / hop)
    max_kick_idx = int(45.0 * sr / hop)
    energy_section = energy[intro_end_idx:min(max_kick_idx, len(energy))]
    
    if len(energy_section) > 0:
        kick_idx = intro_end_idx + np.argmax(energy_section)
        if energy[kick_idx] > 0.5:
            cues.first_kick = times[min(kick_idx, len(times)-1)]
    
    # 3. Detect buildups (gradual energy increases)
    for i in range(1, len(energy)-1):
        slope = energy[i] - energy[i-1]
        if 0.05 < slope < 0.3 and energy[i] > 0.4:
            cues.buildups.append(times[i])
    
    # Remove duplicates (within 2 seconds)
    unique_buildups = []
    for b in cues.buildups:
        if not unique_buildups or abs(b - unique_buildups[-1]) > 2.0:
            unique_buildups.append(b)
    cues.buildups = unique_buildups[:4]  # Max 4 buildups per track
    
    # 4. Detect outro (sustained low energy near end)
    outro_section = energy[-int(30 * sr / hop):]  # Last 30 seconds
    avg_outro_energy = np.mean(outro_section)
    
    if avg_outro_energy < 0.3:
        cues.outro_start = duration - 30.0
    else:
        # Find where energy drops and stays low
        for i in range(len(energy)-1, 0, -1):
            if energy[i] < 0.2:
                cues.outro_start = times[i]
                break
    
    if cues.outro_start is None:
        cues.outro_start = max(duration - 20.0, duration * 0.85)
    
    # Clamp values to valid range [0, duration]
    cues.outro_start = min(max(cues.outro_start, 0.0), duration)
    cues.outro_end = duration
    
    logger.info(f"Smart cues detected - Intro: {cues.intro_end:.1f}s, "
                f"Kick: {cues.first_kick}, Outro: {cues.outro_start:.1f}s")
    
    return cues


def detect_intro_outro(spectrum: np.ndarray, duration: float) -> Tuple[float, float]:
    """
    Detect intro and outro boundaries.
    
    Args:
        spectrum: 1D energy array
        duration: Track duration in seconds
        
    Returns:
        Tuple of (intro_end_seconds, outro_start_seconds)
    """
    # Intro: where energy rises above baseline
    baseline = np.percentile(spectrum, 25)
    intro_end_idx = np.argmax(spectrum > baseline * 1.5)
    intro_end = intro_end_idx * HOP_LENGTH / 44100
    
    # Outro: last 20 seconds where energy is consistently low
    outro_start = max(duration - 20.0, duration * 0.8)
    
    return intro_end, outro_start


# ============================================================================
# SPECTRAL CHARACTERISTICS
# ============================================================================

def spectral_characteristics(
    file_path: str,
    audio_data: Optional[Tuple[np.ndarray, int]] = None,
    config: Optional[DSPConfig] = None,
) -> SpectralCharacteristics:
    """
    Analyze frequency content of an audio file.

    Breaks down energy across frequency bands:
    - Rumble (<20Hz): Sub-bass, rumble, wind noise
    - Bass (20-200Hz): Kick drums, bass instruments
    - Mids (200Hz-2kHz): Vocals, snares, body of mix
    - Treble (2kHz-20kHz): Cymbals, sparkle, presence

    Args:
        file_path: Path to audio file
        audio_data: Optional pre-loaded (audio, sr) tuple from AudioCache
        config: Optional DSPConfig for parameters

    Returns:
        SpectralCharacteristics with frequency breakdown
    """
    logger.debug(f"Analyzing spectral characteristics: {file_path}")

    n_fft = config.fft_size if config else N_FFT
    hop = config.hop_length if config else HOP_LENGTH
    bass_lo = config.bass_freq_low if config else BASS_FREQ_LOW
    bass_hi = config.bass_freq_high if config else BASS_FREQ_HIGH
    mid_lo = config.mid_freq_low if config else MID_FREQ_LOW
    mid_hi = config.mid_freq_high if config else MID_FREQ_HIGH
    treble_lo = config.treble_freq_low if config else TREBLE_FREQ_LOW
    treble_hi = config.treble_freq_high if config else TREBLE_FREQ_HIGH

    # Load audio (or use cached)
    if audio_data is not None:
        audio, sr = audio_data
    else:
        audio, sr = load_audio(file_path)

    # Compute FFT
    S = signal.stft(audio, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    freqs = S[0]
    Sxx = np.abs(S[2])

    # Average power across time
    power = np.mean(Sxx, axis=1)

    # Define frequency band indices
    rumble_mask = freqs < RUMBLE_FREQ_HIGH
    bass_mask = (freqs >= bass_lo) & (freqs < bass_hi)
    mid_mask = (freqs >= mid_lo) & (freqs < mid_hi)
    treble_mask = (freqs >= treble_lo) & (freqs < treble_hi)
    
    # Calculate energy per band
    rumble_energy = np.sum(power[rumble_mask]) if np.any(rumble_mask) else 0
    bass_energy = np.sum(power[bass_mask]) if np.any(bass_mask) else 0
    mid_energy = np.sum(power[mid_mask]) if np.any(mid_mask) else 0
    treble_energy = np.sum(power[treble_mask]) if np.any(treble_mask) else 0
    
    # Normalize (sum to 1.0)
    total = rumble_energy + bass_energy + mid_energy + treble_energy + 1e-10
    rumble_norm = float(rumble_energy / total)
    bass_norm = float(bass_energy / total)
    mid_norm = float(mid_energy / total)
    treble_norm = float(treble_energy / total)
    
    # Detect kick (strong bass energy)
    kick_detected = bass_norm > 0.20
    
    # Detect bassline (sustained bass energy)
    bassline_present = bass_norm > 0.25
    
    logger.debug(f"Spectral: Bass={bass_norm:.2f}, Mid={mid_norm:.2f}, "
                f"Treble={treble_norm:.2f}, Kick={kick_detected}")
    
    return SpectralCharacteristics(
        bass_energy=bass_norm,
        mid_energy=mid_norm,
        treble_energy=treble_norm,
        rumble_presence=rumble_norm,
        kick_detected=kick_detected,
        bassline_present=bassline_present
    )


# ============================================================================
# FULL ANALYSIS
# ============================================================================

def analyze_track(
    file_path: str,
    audio_data: Optional[Tuple[np.ndarray, int]] = None,
    config: Optional[DSPConfig] = None,
) -> Dict:
    """
    Complete spectral and temporal analysis of a track.

    Args:
        file_path: Path to audio file
        audio_data: Optional pre-loaded (audio, sr) tuple from AudioCache
        config: Optional DSPConfig for parameters

    Returns:
        Dict with all analysis results
    """
    logger.info(f"Full analysis: {file_path}")

    # Load audio for duration (or use cached)
    if audio_data is not None:
        audio, sr = audio_data
    else:
        audio, sr = load_audio(file_path)
    duration = len(audio) / sr

    # Get all analyses (reuse same audio_data)
    cached = (audio, sr)
    energy_profile = analyze_energy_profile(file_path, audio_data=cached, config=config)
    smart_cues = identify_smart_cues(file_path, audio_data=cached, config=config)
    spectral = spectral_characteristics(file_path, audio_data=cached, config=config)
    
    return {
        "file": str(file_path),
        "duration_seconds": duration,
        "energy_profile": {
            "peaks": energy_profile.peaks,
            "peak_strengths": energy_profile.peak_strengths,
        },
        "smart_cues": {
            "intro_end": smart_cues.intro_end,
            "first_kick": smart_cues.first_kick,
            "buildups": smart_cues.buildups,
            "drops": smart_cues.drops,
            "outro_start": smart_cues.outro_start,
            "outro_end": smart_cues.outro_end,
        },
        "spectral": {
            "bass_energy": spectral.bass_energy,
            "mid_energy": spectral.mid_energy,
            "treble_energy": spectral.treble_energy,
            "rumble_presence": spectral.rumble_presence,
            "kick_detected": spectral.kick_detected,
            "bassline_present": spectral.bassline_present,
        }
    }


def export_analysis_json(analyses: List[Dict], filepath: str) -> None:
    """
    Export spectral analysis results to JSON.
    
    Args:
        analyses: List of analysis dicts from analyze_track()
        filepath: Output JSON file path
    """
    output = {
        "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
        "phase": 3,
        "phase_name": "Spectral Analysis & Smart Cues",
        "track_count": len(analyses),
        "tracks": analyses
    }
    
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Analysis exported to {filepath}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print("Phase 3 Spectral Analysis Module")
    print("Note: Requires audio files for analysis")
    print("Usage: analyze_track(file_path) returns detailed analysis dict")
