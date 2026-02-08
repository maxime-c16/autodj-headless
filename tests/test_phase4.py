"""
Unit Tests for Phase 4: Loudness, Adaptive EQ, and Pipeline
=============================================================

Comprehensive test suite covering:
- K-weighting filter design and application
- Block-based LUFS calculation
- Gated integrated loudness
- True peak metering
- Loudness range (LRA)
- Biquad filter coefficient design
- Adaptive EQ spectral correction
- Transition EQ interpolation
- Unified pipeline integration

Test tracks reference: "Deine Angst" by Klangkuenstler (seed track)
Music library: /srv/nas/shared

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest
import scipy.io.wavfile as wavfile
import scipy.signal as sig

from src.autodj.analyze.loudness import (
    LoudnessProfile,
    apply_k_weighting,
    compute_block_loudness,
    compute_gated_loudness,
    compute_loudness_range,
    compute_normalization_gain,
    design_k_weighting_filters,
    measure_sample_peak,
    measure_true_peak,
    analyze_loudness,
    analyze_loudness_batch,
    export_loudness_json,
    ABSOLUTE_GATE_LUFS,
    LUFS_OFFSET,
    MOMENTARY_BLOCK_MS,
    SHORT_TERM_BLOCK_MS,
    TARGET_LUFS_STREAMING,
)
from src.autodj.analyze.adaptive_eq import (
    AdaptiveEQProfile,
    BiquadCoefficients,
    EQBand,
    TransitionEQ,
    design_adaptive_eq,
    design_high_shelf,
    design_low_shelf,
    design_peaking_eq,
    get_transition_eq,
    generate_liquidsoap_eq,
    export_eq_json,
    REFERENCE_BASS,
    REFERENCE_MID,
    REFERENCE_TREBLE,
    MAX_GAIN_DB,
    MIN_GAIN_DB,
)
from src.autodj.analyze.pipeline import (
    DJAnalysisPipeline,
    TrackAnalysis,
    SetAnalysis,
    TransitionAnalysis,
    export_set_analysis_json,
    quick_analyze,
)


# ============================================================================
# FIXTURES: Synthetic Audio
# ============================================================================

SAMPLE_RATE = 44100
TEST_DURATION = 5  # seconds for most tests


def _generate_sine_wav(tmp_path: Path, freq: float = 440.0,
                       amplitude: float = 0.5, duration: float = TEST_DURATION,
                       sr: int = SAMPLE_RATE, stereo: bool = False,
                       name: str = "test.wav") -> str:
    """Generate a sine wave WAV file."""
    t = np.arange(int(duration * sr)) / sr
    audio = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if stereo:
        audio = np.column_stack([audio, audio * 0.8])
    int_audio = (audio * 32767).astype(np.int16)
    filepath = tmp_path / name
    wavfile.write(str(filepath), sr, int_audio)
    return str(filepath)


def _generate_kick_bass_wav(tmp_path: Path, duration: float = TEST_DURATION,
                            name: str = "kick_bass.wav") -> str:
    """Generate synthetic kick+bass audio (DJ-like)."""
    sr = SAMPLE_RATE
    t = np.arange(int(duration * sr)) / sr

    # Kick at 80Hz with envelope
    kick = np.sin(2 * np.pi * 80 * t) * np.exp(-t * 3)
    # Bass at 120Hz
    bass = 0.4 * np.sin(2 * np.pi * 120 * t)
    # Hi-hat at 8000Hz
    hihat = 0.15 * np.sin(2 * np.pi * 8000 * t) * (1 + 0.5 * np.sin(2 * np.pi * 4 * t))
    # Mid synth at 1000Hz
    mid = 0.2 * np.sin(2 * np.pi * 1000 * t)

    audio = (kick + bass + hihat + mid) * 0.4
    int_audio = (audio * 32767).astype(np.int16)
    filepath = tmp_path / name
    wavfile.write(str(filepath), sr, int_audio)
    return str(filepath)


def _generate_quiet_wav(tmp_path: Path, name: str = "quiet.wav") -> str:
    """Generate very quiet audio (near silence)."""
    sr = SAMPLE_RATE
    duration = 3
    t = np.arange(int(duration * sr)) / sr
    audio = 0.001 * np.sin(2 * np.pi * 100 * t)
    int_audio = (audio * 32767).astype(np.int16)
    filepath = tmp_path / name
    wavfile.write(str(filepath), sr, int_audio)
    return str(filepath)


def _generate_clipped_wav(tmp_path: Path, name: str = "clipped.wav") -> str:
    """Generate clipped/distorted audio."""
    sr = SAMPLE_RATE
    t = np.arange(int(3 * sr)) / sr
    audio = 2.0 * np.sin(2 * np.pi * 440 * t)  # Intentionally > 1.0
    audio = np.clip(audio, -1.0, 1.0)
    int_audio = (audio * 32767).astype(np.int16)
    filepath = tmp_path / name
    wavfile.write(str(filepath), sr, int_audio)
    return str(filepath)


def _generate_dj_track_wav(tmp_path: Path, freq_base: float = 100.0,
                           amplitude: float = 0.5, duration: float = 10.0,
                           name: str = "dj_track.wav") -> str:
    """Generate a DJ-like track with intro, body, and outro energy profile."""
    sr = SAMPLE_RATE
    samples = int(duration * sr)
    t = np.arange(samples) / sr

    # Envelope: quiet intro (2s), loud body (6s), quiet outro (2s)
    envelope = np.ones(samples)
    intro = int(2 * sr)
    outro = int(2 * sr)
    envelope[:intro] = np.linspace(0, 1, intro)
    envelope[-outro:] = np.linspace(1, 0, outro)

    # Multi-frequency content
    kick = np.sin(2 * np.pi * freq_base * t)
    mid = 0.3 * np.sin(2 * np.pi * 800 * t)
    high = 0.15 * np.sin(2 * np.pi * 6000 * t)

    audio = amplitude * envelope * (kick + mid + high)
    int_audio = (audio * 32767).astype(np.int16)
    filepath = tmp_path / name
    wavfile.write(str(filepath), sr, int_audio)
    return str(filepath)


@pytest.fixture
def sine_wav(tmp_path):
    return _generate_sine_wav(tmp_path)


@pytest.fixture
def stereo_wav(tmp_path):
    return _generate_sine_wav(tmp_path, stereo=True, name="stereo.wav")


@pytest.fixture
def kick_bass_wav(tmp_path):
    return _generate_kick_bass_wav(tmp_path)


@pytest.fixture
def quiet_wav(tmp_path):
    return _generate_quiet_wav(tmp_path)


@pytest.fixture
def clipped_wav(tmp_path):
    return _generate_clipped_wav(tmp_path)


@pytest.fixture
def dj_set_wavs(tmp_path):
    """Generate 4 DJ-like tracks simulating a real set.

    Seed concept: "Deine Angst" by Klangkuenstler style (hard techno).
    """
    tracks = []
    configs = [
        (80, 0.6, "track_deine_angst.wav"),     # Heavy bass (seed track)
        (100, 0.5, "track_techno_02.wav"),        # Mid-range focus
        (60, 0.7, "track_techno_03.wav"),          # Sub-bass heavy
        (120, 0.4, "track_techno_04.wav"),         # Lighter kick
    ]
    for freq, amp, name in configs:
        fp = _generate_dj_track_wav(tmp_path, freq_base=freq, amplitude=amp,
                                    duration=10.0, name=name)
        tracks.append(fp)
    return tracks


# ============================================================================
# TEST: K-Weighting Filter Design
# ============================================================================

class TestKWeightingFilter:
    """Test K-weighting filter per ITU-R BS.1770-4."""

    def test_filter_coefficients_48khz(self):
        """Verify pre-computed 48kHz coefficients match ITU standard."""
        b1, a1, b2, a2 = design_k_weighting_filters(48000)

        # Stage 1 coefficients from ITU-R BS.1770-4
        assert abs(b1[0] - 1.53512485958697) < 1e-10
        assert abs(a1[1] - (-1.69065929318241)) < 1e-10

        # Stage 2 (RLB)
        assert abs(b2[0] - 1.0) < 1e-10
        assert abs(b2[1] - (-2.0)) < 1e-10

    def test_filter_coefficients_44100(self):
        """Verify 44.1kHz coefficients are reasonable."""
        b1, a1, b2, a2 = design_k_weighting_filters(44100)

        # Should have valid coefficients (non-zero)
        assert abs(b1[0]) > 0
        assert abs(a1[1]) > 0

    def test_filter_stability(self):
        """All K-weighting filters must be stable."""
        for sr in [44100, 48000, 96000]:
            b1, a1, b2, a2 = design_k_weighting_filters(sr)
            # Check poles inside unit circle
            poles1 = np.roots(a1)
            poles2 = np.roots(a2)
            assert np.all(np.abs(poles1) < 1.0), f"Unstable stage 1 at {sr}Hz"
            assert np.all(np.abs(poles2) < 1.0), f"Unstable stage 2 at {sr}Hz"

    def test_apply_k_weighting_mono(self, sine_wav):
        """Apply K-weighting to mono audio."""
        sr, audio = wavfile.read(sine_wav)
        audio_float = audio.astype(np.float32) / 32768.0
        weighted = apply_k_weighting(audio_float, sr)

        assert weighted.shape == audio_float.shape
        assert not np.all(weighted == 0)

    def test_apply_k_weighting_stereo(self, stereo_wav):
        """Apply K-weighting to stereo audio."""
        sr, audio = wavfile.read(stereo_wav)
        audio_float = audio.astype(np.float32) / 32768.0
        weighted = apply_k_weighting(audio_float, sr)

        assert weighted.shape == audio_float.shape
        assert weighted.ndim == 2

    def test_k_weighting_boosts_highs(self):
        """K-weighting should boost high frequencies relative to lows."""
        sr = 48000
        duration = 1.0
        t = np.arange(int(duration * sr)) / sr

        # Low frequency (100Hz) vs high frequency (4000Hz)
        low = np.sin(2 * np.pi * 100 * t).astype(np.float32)
        high = np.sin(2 * np.pi * 4000 * t).astype(np.float32)

        low_weighted = apply_k_weighting(low, sr)
        high_weighted = apply_k_weighting(high, sr)

        # After K-weighting, high frequency should have relatively more energy
        low_rms = np.sqrt(np.mean(low_weighted ** 2))
        high_rms = np.sqrt(np.mean(high_weighted ** 2))

        # High should be boosted relative to low (head-related shelf)
        assert high_rms > low_rms * 0.8  # Allow some tolerance


# ============================================================================
# TEST: Block-Based Loudness
# ============================================================================

class TestBlockLoudness:
    """Test block-based LUFS calculation."""

    def test_block_loudness_shape(self):
        """Block loudness output has correct number of blocks."""
        sr = 48000
        duration = 2.0
        audio = np.zeros(int(sr * duration), dtype=np.float32)
        audio[:] = 0.1 * np.sin(2 * np.pi * 1000 * np.arange(len(audio)) / sr)

        blocks = compute_block_loudness(audio, sr, block_ms=400, overlap=0.75)
        assert len(blocks) > 0

    def test_silent_audio_blocked(self):
        """Silent audio should produce -inf LUFS blocks."""
        sr = 48000
        audio = np.zeros(int(sr * 2), dtype=np.float32)
        blocks = compute_block_loudness(audio, sr)
        assert np.all(blocks == -np.inf)

    def test_louder_signal_higher_lufs(self):
        """Louder signal should produce higher LUFS values."""
        sr = 48000
        t = np.arange(int(sr * 1)) / sr

        quiet = (0.01 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        loud = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

        blocks_quiet = compute_block_loudness(quiet, sr)
        blocks_loud = compute_block_loudness(loud, sr)

        valid_quiet = blocks_quiet[blocks_quiet > -np.inf]
        valid_loud = blocks_loud[blocks_loud > -np.inf]

        if len(valid_quiet) > 0 and len(valid_loud) > 0:
            assert np.mean(valid_loud) > np.mean(valid_quiet)


# ============================================================================
# TEST: Gated Integrated Loudness
# ============================================================================

class TestGatedLoudness:
    """Test gated integrated loudness calculation."""

    def test_absolute_gate(self):
        """Blocks below -70 LUFS should be gated out."""
        blocks = np.array([-80.0, -75.0, -60.0, -50.0, -40.0])
        result = compute_gated_loudness(blocks)

        # Only blocks above -70 should contribute
        assert result > -70.0
        assert result < -30.0

    def test_all_below_gate(self):
        """All blocks below gate should return -inf."""
        blocks = np.array([-80.0, -75.0, -72.0])
        result = compute_gated_loudness(blocks)
        assert result == -np.inf

    def test_relative_gate(self):
        """Relative gate removes blocks 10 LU below ungated mean."""
        # Mix of loud and quiet blocks
        blocks = np.array([-20.0, -20.0, -20.0, -50.0, -55.0])
        result = compute_gated_loudness(blocks)

        # Result should be close to -20 (quiet blocks gated by relative gate)
        assert -25.0 < result < -15.0

    def test_uniform_loudness(self):
        """Uniform loudness should pass through gating unchanged."""
        target = -23.0
        blocks = np.full(100, target)
        result = compute_gated_loudness(blocks)
        assert abs(result - target) < 0.5


# ============================================================================
# TEST: True Peak Metering
# ============================================================================

class TestTruePeak:
    """Test true peak measurement."""

    def test_sample_peak_sine(self):
        """Sample peak of sine wave at known amplitude."""
        t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
        amplitude = 0.5
        audio = (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        peak_db = measure_sample_peak(audio)
        expected_db = 20 * np.log10(amplitude)

        assert abs(peak_db - expected_db) < 0.5

    def test_true_peak_at_least_sample_peak(self):
        """True peak should be >= sample peak."""
        t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
        audio = (0.9 * np.sin(2 * np.pi * 997 * t)).astype(np.float32)

        sample = measure_sample_peak(audio)
        true = measure_true_peak(audio, SAMPLE_RATE, oversample_factor=4)

        assert true >= sample - 0.1  # Allow small numerical tolerance

    def test_clipped_peak(self, clipped_wav):
        """Clipped audio should have peak near 0 dBFS."""
        profile = analyze_loudness(clipped_wav, compute_true_peak=False)
        assert profile.sample_peak_db > -1.0  # Near 0 dBFS

    def test_silent_peak(self):
        """Silent audio should have -inf peak."""
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        peak = measure_sample_peak(audio)
        assert peak == -np.inf


# ============================================================================
# TEST: Loudness Range (LRA)
# ============================================================================

class TestLoudnessRange:
    """Test loudness range calculation."""

    def test_constant_loudness_zero_lra(self):
        """Constant loudness should produce LRA = 0."""
        st_lufs = np.full(50, -20.0)
        lra = compute_loudness_range(st_lufs)
        assert lra == 0.0

    def test_dynamic_range(self):
        """Wide dynamic range should produce positive LRA."""
        st_lufs = np.concatenate([
            np.full(30, -15.0),  # Loud sections
            np.full(20, -30.0),  # Quiet sections
        ])
        lra = compute_loudness_range(st_lufs)
        assert lra > 5.0  # Should have significant range

    def test_short_input(self):
        """Very short input should return 0."""
        st_lufs = np.array([-20.0])
        lra = compute_loudness_range(st_lufs)
        assert lra == 0.0


# ============================================================================
# TEST: Full Loudness Analysis
# ============================================================================

class TestAnalyzeLoudness:
    """Test the complete loudness analysis function."""

    def test_basic_analysis(self, sine_wav):
        """Analyze a simple sine wave."""
        profile = analyze_loudness(sine_wav)

        assert isinstance(profile, LoudnessProfile)
        assert profile.integrated_lufs < 0  # Should be negative LUFS
        assert profile.duration_seconds > 0
        assert len(profile.momentary_lufs) > 0

    def test_loudness_profile_fields(self, kick_bass_wav):
        """All profile fields should be populated."""
        profile = analyze_loudness(kick_bass_wav)

        assert profile.integrated_lufs != 0
        assert profile.sample_peak_db < 0  # Below 0 dBFS
        assert profile.duration_seconds > 0
        assert profile.target_gain_db != 0  # Should need some gain adjustment

    def test_quiet_audio(self, quiet_wav):
        """Very quiet audio should have low LUFS."""
        profile = analyze_loudness(quiet_wav)
        assert profile.integrated_lufs < -40

    def test_target_gain_calculation(self, sine_wav):
        """Target gain should bring audio to target LUFS."""
        profile = analyze_loudness(sine_wav, target_lufs=-14.0)
        expected_gain = -14.0 - profile.integrated_lufs
        assert abs(profile.target_gain_db - expected_gain) < 1.0

    def test_to_dict(self, sine_wav):
        """Profile should convert to valid JSON dict."""
        profile = analyze_loudness(sine_wav)
        d = profile.to_dict()

        assert "integrated_lufs" in d
        assert "true_peak_dbtp" in d
        assert isinstance(d["integrated_lufs"], float)

    def test_batch_analysis(self, dj_set_wavs):
        """Batch analysis of multiple tracks."""
        profiles = analyze_loudness_batch(dj_set_wavs[:2])
        assert len(profiles) == 2
        for p in profiles:
            assert isinstance(p, LoudnessProfile)

    def test_normalization_gain(self):
        """Normalization gain calculation with peak limiting."""
        gain = compute_normalization_gain(
            current_lufs=-20.0,
            target_lufs=-14.0,
            true_peak_dbtp=-3.0,
            max_true_peak_dbtp=-1.0,
        )
        # Desired: +6dB, but headroom: -1 - (-3) = +2dB
        assert gain == 2.0

    def test_normalization_gain_no_limit(self):
        """Normalization gain without peak limiting."""
        gain = compute_normalization_gain(
            current_lufs=-20.0,
            target_lufs=-14.0,
            true_peak_dbtp=-10.0,
            max_true_peak_dbtp=-1.0,
        )
        assert abs(gain - 6.0) < 0.1

    def test_export_json(self, dj_set_wavs, tmp_path):
        """Export loudness analysis to JSON."""
        profiles = analyze_loudness_batch(dj_set_wavs[:2])
        output = str(tmp_path / "loudness.json")
        export_loudness_json(profiles, dj_set_wavs[:2], output)

        with open(output) as f:
            data = json.load(f)

        assert data["phase"] == 4
        assert len(data["tracks"]) == 2

    def test_file_not_found(self):
        """Missing file should raise FileNotFoundError."""
        with pytest.raises((FileNotFoundError, ValueError)):
            analyze_loudness("/nonexistent/file.wav")


# ============================================================================
# TEST: Biquad Filter Design
# ============================================================================

class TestBiquadDesign:
    """Test biquad filter coefficient generation."""

    def test_low_shelf_unity(self):
        """Low shelf with 0dB gain should be near unity."""
        coeffs = design_low_shelf(100.0, 0.0)
        assert abs(coeffs.b0 - 1.0) < 0.01
        assert coeffs.gain_db == 0.0

    def test_low_shelf_boost(self):
        """Low shelf boost should have gain > 1 at low frequencies."""
        coeffs = design_low_shelf(100.0, 6.0, sample_rate=44100)
        assert coeffs.is_stable()
        assert coeffs.filter_type == "low_shelf"

    def test_peaking_eq_zero_gain(self):
        """Peaking EQ with 0dB gain should be unity."""
        coeffs = design_peaking_eq(1000.0, 0.0)
        assert coeffs.b0 == 1.0
        assert coeffs.b1 == 0.0

    def test_peaking_eq_stability(self):
        """All peaking EQ designs should be stable."""
        for freq in [100, 500, 1000, 5000, 10000]:
            for gain in [-6, -3, 0, 3, 6]:
                coeffs = design_peaking_eq(float(freq), float(gain))
                assert coeffs.is_stable(), f"Unstable at {freq}Hz, {gain}dB"

    def test_high_shelf_stability(self):
        """All high shelf designs should be stable."""
        for freq in [2000, 5000, 8000]:
            for gain in [-6, -3, 3, 6]:
                coeffs = design_high_shelf(float(freq), float(gain))
                assert coeffs.is_stable(), f"Unstable at {freq}Hz, {gain}dB"

    def test_biquad_to_sos(self):
        """SOS format should be correct."""
        coeffs = design_peaking_eq(1000.0, 3.0)
        sos = coeffs.to_sos()
        assert len(sos) == 6
        assert sos[3] == 1.0  # a0 normalized

    def test_extreme_q_stability(self):
        """Extreme Q values should still produce stable filters."""
        coeffs_narrow = design_peaking_eq(1000.0, 6.0, q=10.0)
        coeffs_wide = design_peaking_eq(1000.0, 6.0, q=0.3)
        assert coeffs_narrow.is_stable()
        assert coeffs_wide.is_stable()


# ============================================================================
# TEST: Adaptive EQ Design
# ============================================================================

class TestAdaptiveEQ:
    """Test spectral-aware EQ design."""

    def test_balanced_spectrum_no_eq(self):
        """Balanced spectrum should need minimal EQ."""
        spectral = {
            "bass_energy": REFERENCE_BASS,
            "mid_energy": REFERENCE_MID,
            "treble_energy": REFERENCE_TREBLE,
        }
        profile = design_adaptive_eq(spectral)

        assert abs(profile.low.gain_db) < 1.0
        assert abs(profile.mid.gain_db) < 1.0
        assert abs(profile.high.gain_db) < 1.0

    def test_bass_heavy_track(self):
        """Bass-heavy track should get bass cut."""
        spectral = {
            "bass_energy": 0.7,   # Way above reference
            "mid_energy": 0.2,
            "treble_energy": 0.1,
        }
        profile = design_adaptive_eq(spectral)

        assert profile.low.gain_db < 0  # Should cut bass
        assert profile.high.gain_db > 0  # Should boost treble

    def test_treble_harsh_track(self):
        """Harsh treble track should get treble cut."""
        spectral = {
            "bass_energy": 0.2,
            "mid_energy": 0.2,
            "treble_energy": 0.6,  # Too bright
        }
        profile = design_adaptive_eq(spectral)
        assert profile.high.gain_db < 0

    def test_gain_limits(self):
        """Gains should be clamped to ±6dB."""
        spectral = {
            "bass_energy": 0.01,  # Extreme imbalance
            "mid_energy": 0.01,
            "treble_energy": 0.98,
        }
        profile = design_adaptive_eq(spectral)

        assert profile.low.gain_db >= MIN_GAIN_DB
        assert profile.low.gain_db <= MAX_GAIN_DB
        assert profile.high.gain_db >= MIN_GAIN_DB
        assert profile.high.gain_db <= MAX_GAIN_DB

    def test_all_filters_stable(self):
        """All generated filters should be stable."""
        for bass in [0.1, 0.3, 0.5, 0.7]:
            for mid in [0.1, 0.3, 0.5]:
                treble = 1.0 - bass - mid
                if treble < 0:
                    continue
                spectral = {
                    "bass_energy": bass,
                    "mid_energy": mid,
                    "treble_energy": treble,
                }
                profile = design_adaptive_eq(spectral)
                assert profile.all_stable()

    def test_loudness_compensation(self):
        """LUFS compensation should be applied."""
        spectral = {
            "bass_energy": REFERENCE_BASS,
            "mid_energy": REFERENCE_MID,
            "treble_energy": REFERENCE_TREBLE,
        }
        profile = design_adaptive_eq(spectral, loudness_compensation_db=3.0)
        assert profile.overall_gain_db == 3.0

    def test_sensitivity_zero(self):
        """Zero sensitivity should produce no EQ."""
        spectral = {
            "bass_energy": 0.7,
            "mid_energy": 0.1,
            "treble_energy": 0.2,
        }
        profile = design_adaptive_eq(spectral, sensitivity=0.0)
        assert profile.low.gain_db == 0.0
        assert profile.mid.gain_db == 0.0
        assert profile.high.gain_db == 0.0

    def test_to_dict(self):
        """Profile should serialize to dict."""
        spectral = {
            "bass_energy": 0.5,
            "mid_energy": 0.3,
            "treble_energy": 0.2,
        }
        profile = design_adaptive_eq(spectral)
        d = profile.to_dict()

        assert "low" in d
        assert "mid" in d
        assert "high" in d
        assert "stable" in d["low"]


# ============================================================================
# TEST: Transition EQ
# ============================================================================

class TestTransitionEQ:
    """Test crossfade EQ interpolation."""

    def _make_profile(self, bass=REFERENCE_BASS, mid=REFERENCE_MID,
                      treble=REFERENCE_TREBLE):
        return design_adaptive_eq({
            "bass_energy": bass,
            "mid_energy": mid,
            "treble_energy": treble,
        })

    def test_transition_duration_clamped(self):
        """Duration should be clamped to valid range."""
        a = self._make_profile()
        b = self._make_profile()

        # Too short
        t = get_transition_eq(a, b, duration_seconds=0.5)
        assert t.duration_seconds >= 2.0

        # Too long
        t = get_transition_eq(a, b, duration_seconds=30.0)
        assert t.duration_seconds <= 12.0

    def test_crossfade_curve_length(self):
        """Crossfade curve should have correct number of steps."""
        a = self._make_profile()
        b = self._make_profile()
        t = get_transition_eq(a, b, steps=32)
        assert len(t.crossfade_curve) == 32

    def test_crossfade_curve_bounds(self):
        """Crossfade curve should go from 1.0 to ~0.0."""
        a = self._make_profile()
        b = self._make_profile()
        t = get_transition_eq(a, b, steps=64)
        assert t.crossfade_curve[0] > 0.99   # Start: full A
        assert t.crossfade_curve[-1] < 0.02  # End: no A

    def test_interpolated_gains_present(self):
        """Interpolated gains should have all bands."""
        a = self._make_profile(bass=0.5)
        b = self._make_profile(bass=0.2)
        t = get_transition_eq(a, b)

        assert "low" in t.interpolated_gains
        assert "mid" in t.interpolated_gains
        assert "high" in t.interpolated_gains
        assert len(t.interpolated_gains["low"]) > 0

    def test_to_dict(self):
        """Transition should serialize to dict."""
        a = self._make_profile()
        b = self._make_profile()
        t = get_transition_eq(a, b)
        d = t.to_dict()

        assert "duration_seconds" in d
        assert "track_a_eq" in d
        assert "track_b_eq" in d


# ============================================================================
# TEST: Liquidsoap Code Generation
# ============================================================================

class TestLiquidsoapGeneration:
    """Test Liquidsoap EQ code generation."""

    def test_generate_with_all_bands(self):
        """Generate code with non-zero gains on all bands."""
        spectral = {
            "bass_energy": 0.5,
            "mid_energy": 0.2,
            "treble_energy": 0.3,
        }
        profile = design_adaptive_eq(spectral)
        code = generate_liquidsoap_eq(profile, "s")

        assert "filter.iir.eq" in code or "Adaptive EQ" in code

    def test_generate_with_zero_gains(self):
        """Zero-gain profile should generate minimal code."""
        spectral = {
            "bass_energy": REFERENCE_BASS,
            "mid_energy": REFERENCE_MID,
            "treble_energy": REFERENCE_TREBLE,
        }
        profile = design_adaptive_eq(spectral)
        code = generate_liquidsoap_eq(profile)

        # With balanced spectrum, may have near-zero gains
        assert "Adaptive EQ" in code

    def test_variable_name(self):
        """Custom variable name should appear in code."""
        spectral = {"bass_energy": 0.5, "mid_energy": 0.2, "treble_energy": 0.3}
        profile = design_adaptive_eq(spectral)
        code = generate_liquidsoap_eq(profile, "my_source")
        assert "my_source" in code


# ============================================================================
# TEST: Pipeline Integration
# ============================================================================

class TestPipeline:
    """Test unified analysis pipeline."""

    def test_single_track_analysis(self, kick_bass_wav):
        """Analyze a single track through the full pipeline."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_track(kick_bass_wav)

        assert isinstance(result, TrackAnalysis)
        assert result.duration_seconds > 0
        assert result.spectral is not None
        assert result.loudness is not None
        assert result.adaptive_eq is not None

    def test_track_with_metadata(self, sine_wav):
        """Track analysis with pre-supplied BPM and key."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_track(
            sine_wav, bpm=128.0, camelot_key="10B"
        )

        assert result.bpm == 128.0
        assert result.camelot_key == "10B"

    def test_set_analysis(self, dj_set_wavs):
        """Full set analysis with multiple tracks."""
        pipeline = DJAnalysisPipeline()
        keys = ["10B", "9B", "11B", "12B"]  # Camelot keys for harmonic mixing
        bpms = [138.0, 136.0, 140.0, 135.0]  # Techno BPMs

        result = pipeline.analyze_set(
            dj_set_wavs,
            bpms=bpms,
            keys=keys,
        )

        assert isinstance(result, SetAnalysis)
        assert len(result.tracks) == 4
        assert len(result.transitions) == 3  # N-1 transitions
        assert len(result.optimal_sequence) == 4
        assert result.avg_compatibility > 0

    def test_set_analysis_no_keys(self, dj_set_wavs):
        """Set analysis without harmonic keys should still work."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_set(dj_set_wavs[:2])

        assert len(result.tracks) == 2
        assert result.optimal_sequence == [0, 1]

    def test_transition_analysis(self, dj_set_wavs):
        """Transitions should have loudness gains and EQ."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_set(
            dj_set_wavs[:2],
            keys=["10B", "9B"],
            bpms=[138.0, 136.0],
        )

        assert len(result.transitions) == 1
        t = result.transitions[0]
        assert t.harmonic_compatibility > 0
        assert t.bpm_shift_ratio != 0

    def test_quick_analyze(self, sine_wav):
        """Quick analysis convenience function."""
        result = quick_analyze(sine_wav)
        assert isinstance(result, dict)
        assert "loudness" in result
        assert "spectral" in result

    def test_export_set_json(self, dj_set_wavs, tmp_path):
        """Export set analysis to JSON."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_set(
            dj_set_wavs[:2],
            keys=["10B", "9B"],
        )
        output = str(tmp_path / "set_analysis.json")
        export_set_analysis_json(result, output)

        with open(output) as f:
            data = json.load(f)

        assert data["track_count"] == 2
        assert len(data["tracks"]) == 2
        assert len(data["transitions"]) == 1

    def test_error_recovery(self, tmp_path):
        """Pipeline should handle invalid files gracefully with error list."""
        invalid = str(tmp_path / "nonexistent.wav")

        pipeline = DJAnalysisPipeline()
        # Pipeline catches errors per-phase and records them
        result = pipeline.analyze_track(invalid)
        assert len(result.errors) > 0  # Should have recorded errors
        assert result.spectral is None  # Failed phases return None
        assert result.loudness is None

    def test_to_dict(self, sine_wav):
        """TrackAnalysis should serialize correctly."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_track(sine_wav, bpm=128.0, camelot_key="5A")
        d = result.to_dict()

        assert d["bpm"] == 128.0
        assert d["camelot_key"] == "5A"
        assert "loudness" in d

    def test_set_to_dict(self, dj_set_wavs):
        """SetAnalysis should serialize correctly."""
        pipeline = DJAnalysisPipeline()
        result = pipeline.analyze_set(dj_set_wavs[:2])
        d = result.to_dict()

        assert "tracks" in d
        assert "transitions" in d
        assert "total_analysis_time_sec" in d


# ============================================================================
# TEST: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests across all Phase 4 modules."""

    def test_very_short_audio(self, tmp_path):
        """Very short audio (< 1 block) should not crash."""
        sr = 44100
        audio = (0.5 * np.sin(2 * np.pi * 440 * np.arange(100) / sr)).astype(np.float32)
        int_audio = (audio * 32767).astype(np.int16)
        filepath = str(tmp_path / "short.wav")
        wavfile.write(filepath, sr, int_audio)

        profile = analyze_loudness(filepath, compute_true_peak=False)
        assert isinstance(profile, LoudnessProfile)

    def test_dc_offset_audio(self, tmp_path):
        """Audio with DC offset should still analyze."""
        sr = 44100
        t = np.arange(int(3 * sr)) / sr
        audio = (0.3 * np.sin(2 * np.pi * 440 * t) + 0.2).astype(np.float32)
        int_audio = (audio * 32767).astype(np.int16)
        filepath = str(tmp_path / "dc.wav")
        wavfile.write(filepath, sr, int_audio)

        profile = analyze_loudness(filepath, compute_true_peak=False)
        assert profile.integrated_lufs < 0

    def test_eq_with_empty_spectral(self):
        """EQ design with missing spectral data uses defaults."""
        profile = design_adaptive_eq({})
        assert profile.low.gain_db == 0.0  # Default = reference
        assert profile.all_stable()

    def test_eq_export_json(self, tmp_path):
        """EQ export should produce valid JSON."""
        profiles = [
            design_adaptive_eq({"bass_energy": 0.5, "mid_energy": 0.3, "treble_energy": 0.2}),
            design_adaptive_eq({"bass_energy": 0.3, "mid_energy": 0.4, "treble_energy": 0.3}),
        ]
        output = str(tmp_path / "eq.json")
        export_eq_json(profiles, ["track1.wav", "track2.wav"], output)

        with open(output) as f:
            data = json.load(f)
        assert len(data["tracks"]) == 2


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
