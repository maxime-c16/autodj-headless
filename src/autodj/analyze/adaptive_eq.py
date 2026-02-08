"""
Phase 4: Adaptive EQ Module (Spectral-Aware Equalization)
==========================================================

Designs per-track and per-transition EQ parameters based on spectral analysis
(Phase 3) and loudness measurement (Phase 4 loudness module). Generates
biquad filter coefficients for Liquidsoap rendering.

Theory:
    Adaptive EQ compensates for spectral imbalances between tracks during
    DJ transitions. By analyzing bass/mid/treble energy distribution and
    loudness, the module designs 3-band parametric EQ curves that:
    1. Normalize frequency balance to a reference curve
    2. Smoothly interpolate EQ settings during crossfades
    3. Prevent frequency masking in the overlap region

    Filter design uses the Audio EQ Cookbook (Robert Bristow-Johnson)
    for biquad coefficient calculation, ensuring stability and
    predictable frequency response.

    Reference: Audio EQ Cookbook (Bristow-Johnson, 2021)
    Reference: ITU-R BS.1770-4 for loudness compensation

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# EQ band center frequencies (Hz)
LOW_BAND_FREQ = 80.0       # Low-shelf center (kick/bass)
MID_BAND_FREQ = 1000.0     # Mid peak center (vocals/body)
HIGH_BAND_FREQ = 8000.0    # High-shelf center (presence/air)

# EQ band boundaries (Hz)
LOW_BAND_RANGE = (20.0, 200.0)
MID_BAND_RANGE = (200.0, 2000.0)
HIGH_BAND_RANGE = (2000.0, 20000.0)

# Default Q factors
LOW_Q_DEFAULT = 0.707      # Butterworth slope (gentle shelf)
MID_Q_DEFAULT = 1.0        # Moderate peaking
HIGH_Q_DEFAULT = 0.707     # Gentle shelf

# Gain limits (dB)
MAX_GAIN_DB = 6.0          # Maximum boost
MIN_GAIN_DB = -6.0         # Maximum cut
GAIN_STEP_DB = 0.5         # Precision step

# Reference spectral balance (normalized energy targets)
REFERENCE_BASS = 0.35      # Ideal bass energy fraction
REFERENCE_MID = 0.40       # Ideal mid energy fraction
REFERENCE_TREBLE = 0.25    # Ideal treble energy fraction

# Transition timing
MIN_TRANSITION_SECONDS = 2.0
MAX_TRANSITION_SECONDS = 12.0
DEFAULT_TRANSITION_SECONDS = 4.0

# Crossfade EQ interpolation steps
INTERPOLATION_STEPS = 64   # Points per transition


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class BiquadCoefficients:
    """Second-order IIR (biquad) filter coefficients.

    Transfer function: H(z) = (b0 + b1*z^-1 + b2*z^-2) / (1 + a1*z^-1 + a2*z^-2)

    Note: a0 is normalized to 1.0 (coefficients are pre-divided).

    Attributes:
        b0, b1, b2: Numerator coefficients
        a1, a2: Denominator coefficients (a0=1.0 implicit)
        frequency: Center/corner frequency in Hz
        gain_db: Gain at center frequency in dB
        q: Quality factor (bandwidth control)
        filter_type: "low_shelf", "peaking", "high_shelf"
    """
    b0: float = 1.0
    b1: float = 0.0
    b2: float = 0.0
    a1: float = 0.0
    a2: float = 0.0
    frequency: float = 1000.0
    gain_db: float = 0.0
    q: float = 0.707
    filter_type: str = "peaking"

    def is_stable(self) -> bool:
        """Check if filter is stable (poles inside unit circle)."""
        # For a 2nd-order section: stable if |a2| < 1 and |a1| < 1 + a2
        return abs(self.a2) < 1.0 and abs(self.a1) < (1.0 + self.a2)

    def to_sos(self) -> np.ndarray:
        """Convert to second-order section format [b0, b1, b2, 1.0, a1, a2]."""
        return np.array([self.b0, self.b1, self.b2, 1.0, self.a1, self.a2])


@dataclass
class EQBand:
    """Single EQ band with parameters and coefficients.

    Attributes:
        name: Band name ("low", "mid", "high")
        frequency: Center/corner frequency in Hz
        gain_db: Applied gain in dB
        q: Quality factor
        filter_type: Biquad filter type
        coefficients: Computed biquad coefficients
        energy_ratio: Input energy / reference energy for this band
    """
    name: str
    frequency: float
    gain_db: float
    q: float
    filter_type: str
    coefficients: BiquadCoefficients
    energy_ratio: float = 1.0


@dataclass
class AdaptiveEQProfile:
    """Complete adaptive EQ profile for a track.

    Attributes:
        low: Low-shelf EQ band (20-200Hz)
        mid: Mid peaking EQ band (200Hz-2kHz)
        high: High-shelf EQ band (2kHz-20kHz)
        overall_gain_db: Master gain adjustment
        spectral_balance: Input spectral balance (bass, mid, treble)
        target_balance: Target spectral balance
        lufs_compensation_db: Gain from loudness analysis
    """
    low: EQBand
    mid: EQBand
    high: EQBand
    overall_gain_db: float = 0.0
    spectral_balance: Dict[str, float] = field(default_factory=dict)
    target_balance: Dict[str, float] = field(default_factory=dict)
    lufs_compensation_db: float = 0.0

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "low": {
                "frequency": self.low.frequency,
                "gain_db": round(self.low.gain_db, 1),
                "q": round(self.low.q, 3),
                "filter_type": self.low.filter_type,
                "energy_ratio": round(self.low.energy_ratio, 3),
                "stable": self.low.coefficients.is_stable(),
            },
            "mid": {
                "frequency": self.mid.frequency,
                "gain_db": round(self.mid.gain_db, 1),
                "q": round(self.mid.q, 3),
                "filter_type": self.mid.filter_type,
                "energy_ratio": round(self.mid.energy_ratio, 3),
                "stable": self.mid.coefficients.is_stable(),
            },
            "high": {
                "frequency": self.high.frequency,
                "gain_db": round(self.high.gain_db, 1),
                "q": round(self.high.q, 3),
                "filter_type": self.high.filter_type,
                "energy_ratio": round(self.high.energy_ratio, 3),
                "stable": self.high.coefficients.is_stable(),
            },
            "overall_gain_db": round(self.overall_gain_db, 1),
            "spectral_balance": {
                k: round(v, 3) for k, v in self.spectral_balance.items()
            },
            "lufs_compensation_db": round(self.lufs_compensation_db, 1),
        }

    def all_stable(self) -> bool:
        """Check if all filter bands are stable."""
        return (
            self.low.coefficients.is_stable()
            and self.mid.coefficients.is_stable()
            and self.high.coefficients.is_stable()
        )


@dataclass
class TransitionEQ:
    """EQ parameters for a crossfade transition between two tracks.

    Attributes:
        track_a_eq: EQ profile for outgoing track
        track_b_eq: EQ profile for incoming track
        duration_seconds: Transition duration
        interpolated_gains: Time-varying gain curves per band
        crossfade_curve: Overall crossfade power curve
    """
    track_a_eq: AdaptiveEQProfile
    track_b_eq: AdaptiveEQProfile
    duration_seconds: float
    interpolated_gains: Dict[str, List[Tuple[float, float, float]]] = field(
        default_factory=dict
    )
    crossfade_curve: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "track_a_eq": self.track_a_eq.to_dict(),
            "track_b_eq": self.track_b_eq.to_dict(),
            "duration_seconds": round(self.duration_seconds, 2),
            "interpolation_steps": len(self.crossfade_curve),
        }


# ============================================================================
# BIQUAD FILTER DESIGN (Audio EQ Cookbook)
# ============================================================================

def design_low_shelf(
    frequency: float,
    gain_db: float,
    q: float = LOW_Q_DEFAULT,
    sample_rate: int = 44100,
) -> BiquadCoefficients:
    """
    Design a low-shelf biquad filter.

    From Audio EQ Cookbook (Bristow-Johnson):
    Low-shelf boosts/cuts frequencies below the corner frequency.

    Args:
        frequency: Corner frequency in Hz
        gain_db: Gain in dB (positive=boost, negative=cut)
        q: Quality factor (0.707 = Butterworth)
        sample_rate: Sample rate in Hz

    Returns:
        BiquadCoefficients for the low-shelf filter
    """
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    alpha = math.sin(w0) / (2.0 * q)

    cos_w0 = math.cos(w0)
    sqrt_A = math.sqrt(A)
    two_sqrt_A_alpha = 2.0 * sqrt_A * alpha

    b0 = A * ((A + 1) - (A - 1) * cos_w0 + two_sqrt_A_alpha)
    b1 = 2.0 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - two_sqrt_A_alpha)
    a0 = (A + 1) + (A - 1) * cos_w0 + two_sqrt_A_alpha
    a1 = -2.0 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - two_sqrt_A_alpha

    return BiquadCoefficients(
        b0=b0 / a0, b1=b1 / a0, b2=b2 / a0,
        a1=a1 / a0, a2=a2 / a0,
        frequency=frequency, gain_db=gain_db, q=q,
        filter_type="low_shelf",
    )


def design_peaking_eq(
    frequency: float,
    gain_db: float,
    q: float = MID_Q_DEFAULT,
    sample_rate: int = 44100,
) -> BiquadCoefficients:
    """
    Design a peaking EQ biquad filter.

    From Audio EQ Cookbook (Bristow-Johnson):
    Boosts/cuts a band of frequencies centered at the given frequency.

    Args:
        frequency: Center frequency in Hz
        gain_db: Gain in dB
        q: Quality factor (higher = narrower band)
        sample_rate: Sample rate in Hz

    Returns:
        BiquadCoefficients for the peaking EQ filter
    """
    if abs(gain_db) < 0.01:
        return BiquadCoefficients(
            frequency=frequency, gain_db=0.0, q=q,
            filter_type="peaking",
        )

    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    alpha = math.sin(w0) / (2.0 * q)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * math.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha / A

    return BiquadCoefficients(
        b0=b0 / a0, b1=b1 / a0, b2=b2 / a0,
        a1=a1 / a0, a2=a2 / a0,
        frequency=frequency, gain_db=gain_db, q=q,
        filter_type="peaking",
    )


def design_high_shelf(
    frequency: float,
    gain_db: float,
    q: float = HIGH_Q_DEFAULT,
    sample_rate: int = 44100,
) -> BiquadCoefficients:
    """
    Design a high-shelf biquad filter.

    From Audio EQ Cookbook (Bristow-Johnson):
    High-shelf boosts/cuts frequencies above the corner frequency.

    Args:
        frequency: Corner frequency in Hz
        gain_db: Gain in dB
        q: Quality factor
        sample_rate: Sample rate in Hz

    Returns:
        BiquadCoefficients for the high-shelf filter
    """
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    alpha = math.sin(w0) / (2.0 * q)

    cos_w0 = math.cos(w0)
    sqrt_A = math.sqrt(A)
    two_sqrt_A_alpha = 2.0 * sqrt_A * alpha

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + two_sqrt_A_alpha)
    b1 = -2.0 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - two_sqrt_A_alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + two_sqrt_A_alpha
    a1 = 2.0 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - two_sqrt_A_alpha

    return BiquadCoefficients(
        b0=b0 / a0, b1=b1 / a0, b2=b2 / a0,
        a1=a1 / a0, a2=a2 / a0,
        frequency=frequency, gain_db=gain_db, q=q,
        filter_type="high_shelf",
    )


# ============================================================================
# SPECTRAL-AWARE EQ DESIGN
# ============================================================================

def _quantize_gain(gain_db: float) -> float:
    """Quantize gain to GAIN_STEP_DB steps and clamp to limits."""
    clamped = max(MIN_GAIN_DB, min(MAX_GAIN_DB, gain_db))
    return round(clamped / GAIN_STEP_DB) * GAIN_STEP_DB


def _compute_band_gain(
    energy: float,
    reference: float,
    sensitivity: float = 1.0,
) -> float:
    """
    Compute EQ gain for a frequency band based on energy deviation.

    If band energy is below reference, apply boost.
    If band energy is above reference, apply cut.

    Args:
        energy: Measured band energy (0.0-1.0 normalized)
        reference: Target band energy (0.0-1.0 normalized)
        sensitivity: Gain scaling factor (1.0 = standard)

    Returns:
        Gain in dB (clamped to ±6dB)
    """
    if energy <= 0 or reference <= 0:
        return 0.0

    # Ratio: how much energy differs from reference
    ratio = reference / energy

    # Convert ratio to dB gain
    gain_db = 10.0 * math.log10(ratio) * sensitivity

    return _quantize_gain(gain_db)


def _compute_q_from_deviation(
    energy: float,
    reference: float,
) -> float:
    """
    Compute Q factor based on energy deviation.

    Larger deviations get wider Q (more aggressive correction).
    Small deviations get narrower Q (surgical precision).

    Args:
        energy: Band energy
        reference: Reference energy

    Returns:
        Q factor (0.5-3.0 range)
    """
    if energy <= 0 or reference <= 0:
        return 1.0

    deviation = abs(energy - reference) / reference

    if deviation < 0.1:
        return 2.0   # Very narrow: subtle correction
    elif deviation < 0.3:
        return 1.0   # Medium: moderate correction
    elif deviation < 0.5:
        return 0.707  # Butterworth: standard correction
    else:
        return 0.5   # Wide: aggressive correction


def design_adaptive_eq(
    spectral_data: Dict[str, float],
    loudness_compensation_db: float = 0.0,
    sample_rate: int = 44100,
    sensitivity: float = 0.7,
) -> AdaptiveEQProfile:
    """
    Design a 3-band adaptive EQ based on spectral analysis.

    Takes spectral energy distribution from Phase 3 and designs
    EQ curves that normalize frequency balance toward a reference
    target, with optional loudness compensation from Phase 4.

    Args:
        spectral_data: Dict with keys "bass_energy", "mid_energy", "treble_energy"
                       (normalized 0.0-1.0 from spectral.py)
        loudness_compensation_db: Additional gain from loudness normalization
        sample_rate: Audio sample rate in Hz
        sensitivity: EQ sensitivity (0.0=none, 1.0=full correction)

    Returns:
        AdaptiveEQProfile with 3-band EQ design
    """
    bass = spectral_data.get("bass_energy", REFERENCE_BASS)
    mid = spectral_data.get("mid_energy", REFERENCE_MID)
    treble = spectral_data.get("treble_energy", REFERENCE_TREBLE)

    # Compute per-band gains
    low_gain = _compute_band_gain(bass, REFERENCE_BASS, sensitivity)
    mid_gain = _compute_band_gain(mid, REFERENCE_MID, sensitivity)
    high_gain = _compute_band_gain(treble, REFERENCE_TREBLE, sensitivity)

    # Compute Q factors
    low_q = _compute_q_from_deviation(bass, REFERENCE_BASS)
    mid_q = _compute_q_from_deviation(mid, REFERENCE_MID)
    high_q = _compute_q_from_deviation(treble, REFERENCE_TREBLE)

    # Design biquad filters
    low_coeffs = design_low_shelf(LOW_BAND_FREQ, low_gain, low_q, sample_rate)
    mid_coeffs = design_peaking_eq(MID_BAND_FREQ, mid_gain, mid_q, sample_rate)
    high_coeffs = design_high_shelf(HIGH_BAND_FREQ, high_gain, high_q, sample_rate)

    # Create EQ bands
    low_band = EQBand(
        name="low", frequency=LOW_BAND_FREQ, gain_db=low_gain,
        q=low_q, filter_type="low_shelf", coefficients=low_coeffs,
        energy_ratio=bass / REFERENCE_BASS if REFERENCE_BASS > 0 else 1.0,
    )
    mid_band = EQBand(
        name="mid", frequency=MID_BAND_FREQ, gain_db=mid_gain,
        q=mid_q, filter_type="peaking", coefficients=mid_coeffs,
        energy_ratio=mid / REFERENCE_MID if REFERENCE_MID > 0 else 1.0,
    )
    high_band = EQBand(
        name="high", frequency=HIGH_BAND_FREQ, gain_db=high_gain,
        q=high_q, filter_type="high_shelf", coefficients=high_coeffs,
        energy_ratio=treble / REFERENCE_TREBLE if REFERENCE_TREBLE > 0 else 1.0,
    )

    # Check stability
    for band in [low_band, mid_band, high_band]:
        if not band.coefficients.is_stable():
            logger.warning(
                f"Unstable {band.name} filter at {band.frequency}Hz, "
                f"gain={band.gain_db}dB - resetting to unity"
            )
            band.coefficients = BiquadCoefficients(
                frequency=band.frequency, gain_db=0.0,
                q=band.q, filter_type=band.filter_type,
            )
            band.gain_db = 0.0

    profile = AdaptiveEQProfile(
        low=low_band,
        mid=mid_band,
        high=high_band,
        overall_gain_db=_quantize_gain(loudness_compensation_db),
        spectral_balance={"bass": bass, "mid": mid, "treble": treble},
        target_balance={
            "bass": REFERENCE_BASS, "mid": REFERENCE_MID,
            "treble": REFERENCE_TREBLE,
        },
        lufs_compensation_db=loudness_compensation_db,
    )

    logger.debug(
        f"Adaptive EQ: Low={low_gain:+.1f}dB@{LOW_BAND_FREQ}Hz, "
        f"Mid={mid_gain:+.1f}dB@{MID_BAND_FREQ}Hz, "
        f"High={high_gain:+.1f}dB@{HIGH_BAND_FREQ}Hz"
    )

    return profile


# ============================================================================
# TRANSITION EQ (Crossfade Interpolation)
# ============================================================================

def _equal_power_crossfade(position: float) -> Tuple[float, float]:
    """
    Compute equal-power crossfade gains.

    Uses sine/cosine curves for constant-power crossfading.

    Args:
        position: Crossfade position (0.0 = full A, 1.0 = full B)

    Returns:
        Tuple of (gain_a, gain_b) in linear scale
    """
    position = max(0.0, min(1.0, position))
    gain_a = math.cos(position * math.pi / 2.0)
    gain_b = math.sin(position * math.pi / 2.0)
    return gain_a, gain_b


def _interpolate_gain(
    gain_a: float,
    gain_b: float,
    position: float,
) -> float:
    """
    Interpolate between two EQ gain values.

    Uses linear interpolation in dB domain (perceptually smooth).

    Args:
        gain_a: Starting gain in dB
        gain_b: Ending gain in dB
        position: Interpolation position (0.0-1.0)

    Returns:
        Interpolated gain in dB
    """
    return gain_a + (gain_b - gain_a) * position


def get_transition_eq(
    profile_a: AdaptiveEQProfile,
    profile_b: AdaptiveEQProfile,
    duration_seconds: float = DEFAULT_TRANSITION_SECONDS,
    steps: int = INTERPOLATION_STEPS,
) -> TransitionEQ:
    """
    Compute transition EQ parameters for crossfading between two tracks.

    Generates time-varying EQ gain curves that smoothly transition from
    track A's EQ to track B's EQ over the specified duration. Uses
    equal-power crossfading for the amplitude and linear interpolation
    for EQ gains.

    DJ mixing convention:
    - Cut bass on outgoing track (avoid low-end buildup)
    - Maintain mids during overlap
    - Blend treble smoothly

    Args:
        profile_a: EQ profile for outgoing track
        profile_b: EQ profile for incoming track
        duration_seconds: Transition duration in seconds
        steps: Number of interpolation steps

    Returns:
        TransitionEQ with interpolated EQ curves
    """
    duration_seconds = max(
        MIN_TRANSITION_SECONDS,
        min(MAX_TRANSITION_SECONDS, duration_seconds),
    )

    # Generate interpolated gains per band
    interpolated = {
        "low": [],
        "mid": [],
        "high": [],
    }
    crossfade = []

    for i in range(steps):
        position = i / max(1, steps - 1)

        # Equal-power crossfade curve
        gain_a, gain_b = _equal_power_crossfade(position)
        crossfade.append(float(gain_a))

        # DJ convention: cut bass aggressively on outgoing track
        # to prevent low-end buildup during transition
        bass_a_adj = profile_a.low.gain_db - (position * 6.0)  # Fade bass out
        bass_b_adj = profile_b.low.gain_db - ((1.0 - position) * 6.0)  # Fade bass in

        low_a = _quantize_gain(bass_a_adj)
        low_b = _quantize_gain(bass_b_adj)

        mid_interp = _interpolate_gain(
            profile_a.mid.gain_db, profile_b.mid.gain_db, position
        )
        high_interp = _interpolate_gain(
            profile_a.high.gain_db, profile_b.high.gain_db, position
        )

        time_sec = position * duration_seconds
        interpolated["low"].append((time_sec, low_a, low_b))
        interpolated["mid"].append((time_sec, mid_interp, mid_interp))
        interpolated["high"].append((time_sec, high_interp, high_interp))

    transition = TransitionEQ(
        track_a_eq=profile_a,
        track_b_eq=profile_b,
        duration_seconds=duration_seconds,
        interpolated_gains=interpolated,
        crossfade_curve=crossfade,
    )

    logger.debug(
        f"Transition EQ: {duration_seconds:.1f}s, {steps} steps, "
        f"Bass cut: {profile_a.low.gain_db:+.1f}→-6.0→{profile_b.low.gain_db:+.1f}dB"
    )

    return transition


# ============================================================================
# LIQUIDSOAP EQ CODE GENERATION
# ============================================================================

def generate_liquidsoap_eq(
    profile: AdaptiveEQProfile,
    variable_name: str = "track",
) -> str:
    """
    Generate Liquidsoap code for applying the adaptive EQ.

    Generates filter.iir.eq.low_shelf, filter.iir.eq.peaking,
    and filter.iir.eq.high_shelf calls compatible with Liquidsoap 2.2+.

    Args:
        profile: Adaptive EQ profile
        variable_name: Liquidsoap variable name for the source

    Returns:
        Liquidsoap code string
    """
    lines = [
        f"# Adaptive EQ for {variable_name}",
        f"# Bass: {profile.low.gain_db:+.1f}dB @ {profile.low.frequency}Hz",
        f"# Mid:  {profile.mid.gain_db:+.1f}dB @ {profile.mid.frequency}Hz",
        f"# High: {profile.high.gain_db:+.1f}dB @ {profile.high.frequency}Hz",
    ]

    if abs(profile.low.gain_db) > 0.1:
        lines.append(
            f'{variable_name} = filter.iir.eq.low_shelf('
            f'frequency={profile.low.frequency}, '
            f'gain={profile.low.gain_db}, '
            f'q={profile.low.q:.3f}, '
            f'{variable_name})'
        )

    if abs(profile.mid.gain_db) > 0.1:
        lines.append(
            f'{variable_name} = filter.iir.eq.peak('
            f'frequency={profile.mid.frequency}, '
            f'gain={profile.mid.gain_db}, '
            f'q={profile.mid.q:.3f}, '
            f'{variable_name})'
        )

    if abs(profile.high.gain_db) > 0.1:
        lines.append(
            f'{variable_name} = filter.iir.eq.high_shelf('
            f'frequency={profile.high.frequency}, '
            f'gain={profile.high.gain_db}, '
            f'q={profile.high.q:.3f}, '
            f'{variable_name})'
        )

    if abs(profile.overall_gain_db) > 0.1:
        linear_gain = 10.0 ** (profile.overall_gain_db / 20.0)
        lines.append(
            f'{variable_name} = amplify({linear_gain:.4f}, {variable_name})'
        )

    return "\n".join(lines)


# ============================================================================
# EXPORT
# ============================================================================

def export_eq_json(
    profiles: List[AdaptiveEQProfile],
    filepaths: List[str],
    output_path: str,
) -> None:
    """
    Export adaptive EQ analysis results to JSON.

    Args:
        profiles: List of AdaptiveEQProfile objects
        filepaths: Corresponding file paths
        output_path: Output JSON file path
    """
    output = {
        "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
        "phase": 4,
        "phase_name": "Adaptive EQ Design",
        "track_count": len(profiles),
        "reference_balance": {
            "bass": REFERENCE_BASS,
            "mid": REFERENCE_MID,
            "treble": REFERENCE_TREBLE,
        },
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

    logger.info(f"Adaptive EQ analysis exported to {output_path}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Phase 4 Adaptive EQ Module")
    print("Usage: design_adaptive_eq(spectral_data) -> AdaptiveEQProfile")
    print(f"Reference balance: Bass={REFERENCE_BASS}, Mid={REFERENCE_MID}, "
          f"Treble={REFERENCE_TREBLE}")
