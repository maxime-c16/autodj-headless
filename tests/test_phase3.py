"""
Unit Tests for Phase 3: Spectral Analysis & Smart Cue Detection
================================================================

Comprehensive test suite with ≥80% code coverage.
Tests cover: energy profile analysis, peak detection, smart cue identification,
spectral characteristics analysis, and JSON export.
"""

import pytest
import numpy as np
import tempfile
from pathlib import Path
import json
import logging

from src.autodj.analyze.spectral import (
    SmartCues,
    SpectralCharacteristics,
    EnergyProfile,
    analyze_energy_profile,
    detect_energy_peaks,
    identify_smart_cues,
    detect_intro_outro,
    spectral_characteristics,
    analyze_track,
    export_analysis_json,
    load_audio,
    SAMPLE_RATE,
    HOP_LENGTH,
)


# ============================================================================
# FIXTURES: Synthetic Audio Generation
# ============================================================================

@pytest.fixture
def synthetic_audio_wav(tmp_path):
    """Create a synthetic audio file for testing."""
    import scipy.io.wavfile as wavfile
    
    # Generate synthetic audio: kick drum + bass
    duration = 10  # seconds
    sr = SAMPLE_RATE
    t = np.arange(duration * sr) / sr
    
    # Kick drum: 80Hz sine wave with envelope
    kick_freq = 80
    kick = np.sin(2 * np.pi * kick_freq * t)
    # Envelope: sharp attack, exponential decay
    kick_env = np.exp(-t * 2) * (1 + 0.3 * np.sin(2 * np.pi * 2 * t))
    kick = kick * kick_env
    
    # Bass: 40Hz sine wave
    bass_freq = 40
    bass = 0.5 * np.sin(2 * np.pi * bass_freq * t)
    
    # Combine
    audio = (kick + bass) * 0.5
    audio = (audio * 32767).astype(np.int16)
    
    filepath = tmp_path / "test_audio.wav"
    wavfile.write(filepath, sr, audio)
    
    return str(filepath)


@pytest.fixture
def synthetic_quiet_audio_wav(tmp_path):
    """Create a quiet synthetic audio file."""
    import scipy.io.wavfile as wavfile
    
    duration = 10
    sr = SAMPLE_RATE
    t = np.arange(duration * sr) / sr
    
    # Very quiet sine wave
    audio = 0.05 * np.sin(2 * np.pi * 440 * t)
    audio = (audio * 32767).astype(np.int16)
    
    filepath = tmp_path / "quiet_audio.wav"
    wavfile.write(filepath, sr, audio)
    
    return str(filepath)


@pytest.fixture
def synthetic_energy_peaks():
    """Create synthetic energy profile with known peaks."""
    # Create simple energy signal with 3 peaks
    time = np.linspace(0, 10, 1000)
    energy = (
        0.3 * np.exp(-((time - 2) ** 2) / 0.5) +      # Peak 1 at t=2
        0.4 * np.exp(-((time - 5) ** 2) / 0.5) +      # Peak 2 at t=5
        0.5 * np.exp(-((time - 8) ** 2) / 0.5) +      # Peak 3 at t=8
        0.1 * np.random.default_rng(42).standard_normal(1000)  # Seeded, deterministic
    )
    energy = np.clip(energy, 0, 1)
    return energy


@pytest.fixture
def synthetic_stereo_wav(tmp_path):
    """Generate stereo WAV to test stereo-to-mono downmix."""
    import scipy.io.wavfile as wavfile

    sr = 44100
    t = np.linspace(0, 2, sr * 2, dtype=np.float32)
    left = 0.5 * np.sin(2 * np.pi * 440 * t)
    right = 0.5 * np.sin(2 * np.pi * 880 * t)
    stereo = (np.column_stack([left, right]) * 32767).astype(np.int16)
    wav_path = tmp_path / "stereo.wav"
    wavfile.write(str(wav_path), sr, stereo)
    return str(wav_path)


@pytest.fixture
def synthetic_48k_wav(tmp_path):
    """Generate 48kHz WAV to test sample rate warning."""
    import scipy.io.wavfile as wavfile

    sr = 48000
    t = np.linspace(0, 1, sr, dtype=np.float32)
    audio = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    path = tmp_path / "audio_48k.wav"
    wavfile.write(str(path), sr, audio)
    return str(path)


# ============================================================================
# TEST: Audio Loading
# ============================================================================

class TestAudioLoading:
    """Test audio file loading."""
    
    def test_load_wav_file(self, synthetic_audio_wav):
        """Load WAV file successfully."""
        audio, sr = load_audio(synthetic_audio_wav)
        assert isinstance(audio, np.ndarray)
        assert sr == SAMPLE_RATE
        assert len(audio) > 0
    
    def test_file_not_found(self):
        """Raise error for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_audio("/nonexistent/file.wav")
    
    def test_audio_is_float(self, synthetic_audio_wav):
        """Audio is normalized to float."""
        audio, _ = load_audio(synthetic_audio_wav)
        assert audio.dtype in [np.float32, np.float64]


class TestStereoLoading:
    """Test stereo WAV downmix to mono."""

    def test_stereo_downmixed_to_mono(self, synthetic_stereo_wav):
        audio, sr = load_audio(synthetic_stereo_wav)
        assert audio.ndim == 1, "Stereo should be downmixed to mono"
        assert audio.dtype == np.float32
        assert -1.0 <= audio.min() and audio.max() <= 1.0


def test_non_standard_sample_rate_loads_with_warning(synthetic_48k_wav, caplog):
    """Non-44100Hz WAV should load but log a warning."""
    with caplog.at_level(logging.WARNING):
        audio, sr = load_audio(synthetic_48k_wav)
    assert sr == 48000
    assert audio.dtype == np.float32
    assert any("SR" in r.message or "44100" in r.message for r in caplog.records)


# ============================================================================
# TEST: Energy Profile Analysis
# ============================================================================

class TestEnergyProfileAnalysis:
    """Test energy profile computation."""
    
    def test_energy_profile_shape(self, synthetic_audio_wav):
        """Energy profile returns correct shapes."""
        profile = analyze_energy_profile(synthetic_audio_wav)
        
        assert isinstance(profile, EnergyProfile)
        assert isinstance(profile.energy_timeline, np.ndarray)
        assert len(profile.energy_timeline) > 0
        assert len(profile.time_axis) == len(profile.energy_timeline)
    
    def test_energy_normalized(self, synthetic_audio_wav):
        """Energy values are normalized (0-1)."""
        profile = analyze_energy_profile(synthetic_audio_wav)
        assert np.all(profile.energy_timeline >= 0)
        assert np.all(profile.energy_timeline <= 1)
    
    def test_peaks_detected(self, synthetic_audio_wav):
        """Peaks are detected in energy profile."""
        profile = analyze_energy_profile(synthetic_audio_wav)
        assert len(profile.peaks) > 0
        assert len(profile.peak_strengths) == len(profile.peaks)
    
    def test_peak_strengths_normalized(self, synthetic_audio_wav):
        """Peak strengths are valid confidence scores."""
        profile = analyze_energy_profile(synthetic_audio_wav)
        for strength in profile.peak_strengths:
            assert 0.0 <= strength <= 1.0


# ============================================================================
# TEST: Peak Detection
# ============================================================================

class TestPeakDetection:
    """Test energy peak detection."""
    
    def test_detect_peaks_basic(self, synthetic_energy_peaks):
        """Detect peaks in synthetic signal."""
        peaks = detect_energy_peaks(synthetic_energy_peaks, threshold=0.3)
        assert len(peaks) > 0
    
    def test_threshold_impact(self, synthetic_energy_peaks):
        """Higher threshold = fewer peaks."""
        peaks_low = detect_energy_peaks(synthetic_energy_peaks, threshold=0.2)
        peaks_high = detect_energy_peaks(synthetic_energy_peaks, threshold=0.8)
        assert len(peaks_low) >= len(peaks_high)
    
    def test_invalid_threshold(self, synthetic_energy_peaks):
        """Reject invalid threshold values."""
        with pytest.raises(ValueError):
            detect_energy_peaks(synthetic_energy_peaks, threshold=1.5)
        with pytest.raises(ValueError):
            detect_energy_peaks(synthetic_energy_peaks, threshold=-0.1)


# ============================================================================
# TEST: Smart Cue Detection
# ============================================================================

class TestSmartCueDetection:
    """Test smart cue point identification."""
    
    def test_smart_cues_structure(self, synthetic_audio_wav):
        """Smart cues have required fields."""
        cues = identify_smart_cues(synthetic_audio_wav)
        
        assert isinstance(cues, SmartCues)
        assert hasattr(cues, "intro_end")
        assert hasattr(cues, "first_kick")
        assert hasattr(cues, "buildups")
        assert hasattr(cues, "outro_start")
        assert hasattr(cues, "outro_end")
    
    def test_cues_valid_range(self, synthetic_audio_wav):
        """Cue points are within file duration."""
        # Load to get duration
        audio, sr = load_audio(synthetic_audio_wav)
        duration = len(audio) / sr
        
        cues = identify_smart_cues(synthetic_audio_wav)
        
        assert cues.intro_end is None or 0 <= cues.intro_end <= duration
        assert cues.first_kick is None or 0 <= cues.first_kick <= duration
        assert cues.outro_start is None or 0 <= cues.outro_start <= duration
        assert 0 <= cues.outro_end <= duration + 1  # Small tolerance
    
    def test_intro_before_outro(self, synthetic_audio_wav):
        """Intro end comes before outro start."""
        cues = identify_smart_cues(synthetic_audio_wav)
        
        if cues.intro_end is not None and cues.outro_start is not None:
            assert cues.intro_end < cues.outro_start
    
    def test_buildups_in_chronological_order(self, synthetic_audio_wav):
        """Buildups are sorted by time."""
        cues = identify_smart_cues(synthetic_audio_wav)
        
        if len(cues.buildups) > 1:
            for i in range(len(cues.buildups) - 1):
                assert cues.buildups[i] < cues.buildups[i + 1]


# ============================================================================
# TEST: Intro/Outro Detection
# ============================================================================

class TestIntroOutroDetection:
    """Test intro and outro boundary detection."""
    
    def test_intro_outro_values(self, synthetic_energy_peaks):
        """Intro and outro are valid timestamps."""
        duration = 10.0
        intro, outro = detect_intro_outro(synthetic_energy_peaks, duration)
        
        assert 0 <= intro <= duration
        assert 0 <= outro <= duration
        assert intro < outro


# ============================================================================
# TEST: Spectral Characteristics
# ============================================================================

class TestSpectralCharacteristics:
    """Test frequency content analysis."""
    
    def test_spectral_structure(self, synthetic_audio_wav):
        """Spectral characteristics returned correctly."""
        spec = spectral_characteristics(synthetic_audio_wav)
        
        assert isinstance(spec, SpectralCharacteristics)
        assert hasattr(spec, "bass_energy")
        assert hasattr(spec, "mid_energy")
        assert hasattr(spec, "treble_energy")
        assert hasattr(spec, "kick_detected")
    
    def test_energy_normalized(self, synthetic_audio_wav):
        """Frequency energies are normalized (0-1)."""
        spec = spectral_characteristics(synthetic_audio_wav)
        
        assert 0 <= spec.bass_energy <= 1.0
        assert 0 <= spec.mid_energy <= 1.0
        assert 0 <= spec.treble_energy <= 1.0
        assert 0 <= spec.rumble_presence <= 1.0
    
    def test_kick_detection_on_kickdrum_audio(self, synthetic_audio_wav):
        """Detect kick in kick drum audio."""
        spec = spectral_characteristics(synthetic_audio_wav)
        # Synthetic audio has strong 80Hz kick — must be detected
        assert spec.kick_detected, (
            f"Expected kick detected in kick drum audio, bass_energy={spec.bass_energy:.3f}"
        )

    def test_quiet_audio_no_kick(self, synthetic_quiet_audio_wav):
        """No kick detected in quiet audio."""
        spec = spectral_characteristics(synthetic_quiet_audio_wav)
        assert not spec.kick_detected, (
            f"No kick expected in quiet audio, bass_energy={spec.bass_energy:.3f}"
        )


# ============================================================================
# TEST: Full Track Analysis
# ============================================================================

class TestFullTrackAnalysis:
    """Test complete track analysis."""
    
    def test_analyze_track_structure(self, synthetic_audio_wav):
        """Full analysis returns expected structure."""
        result = analyze_track(synthetic_audio_wav)
        
        assert "file" in result
        assert "duration_seconds" in result
        assert "energy_profile" in result
        assert "smart_cues" in result
        assert "spectral" in result
    
    def test_analysis_completeness(self, synthetic_audio_wav):
        """All required fields present in analysis."""
        result = analyze_track(synthetic_audio_wav)
        
        # Check smart_cues
        cues = result["smart_cues"]
        assert "intro_end" in cues
        assert "first_kick" in cues
        assert "buildups" in cues
        assert "outro_start" in cues
        
        # Check spectral
        spec = result["spectral"]
        assert "bass_energy" in spec
        assert "mid_energy" in spec
        assert "treble_energy" in spec
        assert "kick_detected" in spec


# ============================================================================
# TEST: JSON Export
# ============================================================================

class TestJsonExport:
    """Test JSON export functionality."""
    
    def test_export_creates_valid_json(self, synthetic_audio_wav):
        """Export produces valid JSON file."""
        analysis = analyze_track(synthetic_audio_wav)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "analysis.json"
            export_analysis_json([analysis], str(filepath))
            
            assert filepath.exists()
            
            # Verify it's valid JSON
            with open(filepath) as f:
                data = json.load(f)
            
            assert "analysis_timestamp" in data
            assert "phase" in data
            assert data["phase"] == 3
            assert "tracks" in data
    
    def test_export_timestamp_format(self, synthetic_audio_wav):
        """Timestamp is ISO format with Z."""
        analysis = analyze_track(synthetic_audio_wav)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "analysis.json"
            export_analysis_json([analysis], str(filepath))
            
            with open(filepath) as f:
                data = json.load(f)
            
            timestamp = data["analysis_timestamp"]
            assert "T" in timestamp
            assert timestamp.endswith("Z")


# ============================================================================
# INTEGRATION TEST: Real Track Analysis
# ============================================================================

class TestPhase3RealTracks:
    """Integration test with real DJ tracks (if available)."""
    
    def test_phase3_synthetic_track(self, synthetic_audio_wav):
        """
        Test spectral analysis on synthetic track.
        
        This integration test validates that all Phase 3 components
        work together correctly on a representative audio file.
        """
        # Full analysis
        result = analyze_track(synthetic_audio_wav)
        
        # Verify structure
        assert result["duration_seconds"] > 0
        assert len(result["energy_profile"]["peaks"]) > 0
        
        # Verify smart cues
        cues = result["smart_cues"]
        assert cues["outro_end"] > cues["intro_end"]
        
        # Verify spectral
        spec = result["spectral"]
        energy_sum = (spec["bass_energy"] + spec["mid_energy"] + 
                     spec["treble_energy"] + spec["rumble_presence"])
        assert 0.9 <= energy_sum <= 1.1  # Allow small rounding error
        
        # Verify spectral detection
        assert isinstance(spec["kick_detected"], bool)
        assert isinstance(spec["bassline_present"], bool)
        
        print("✅ Phase 3 synthetic track analysis passed")


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
