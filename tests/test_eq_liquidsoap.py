"""
Tests for Liquidsoap DSP code generation (Phase 2).

Verifies that:
1. DSP code generates syntactically valid Liquidsoap
2. EQ opportunities are converted to correct filter calls
3. Timing (bar positions → sample positions) is accurate
4. Envelopes are properly calculated
5. Track bounds are respected
"""

import pytest
import json
from pathlib import Path

from autodj.render.eq_liquidsoap import EQLiquidsoap
from autodj.render.eq_automation import (
    EQOpportunity,
    EQCutType,
    FrequencyBand,
    EQEnvelope,
    EQAutomationEngine,
    EQAutomationDetector,
)


class TestEQLiquidsoap:
    """Test Liquidsoap DSP code generation."""
    
    @pytest.fixture
    def dsp_gen(self):
        """Create DSP generator at 128 BPM, 44100 Hz."""
        return EQLiquidsoap(bpm=128.0, sample_rate=44100)
    
    def test_init(self, dsp_gen):
        """Test initialization and sample rate calculations."""
        assert dsp_gen.bpm == 128.0
        assert dsp_gen.sample_rate == 44100
        # 128 BPM: 240 / 128 = 1.875 seconds/bar
        assert abs(dsp_gen.seconds_per_bar - 1.875) < 0.001
        # 1.875 * 44100 = 82687.5 ≈ 82687 or 82688 samples/bar
        assert abs(dsp_gen.samples_per_bar - 82688) <= 1
    
    def test_identity_dsp_no_opportunities(self, dsp_gen):
        """Test that no opportunities generates identity function."""
        code = dsp_gen.generate_dsp_chain([], 32, "Test Track")
        
        assert "eq_dsp" in code
        assert "let eq_dsp = fun(s) -> s" in code
        assert "Test Track" in code
    
    def test_bass_cut_generation(self, dsp_gen):
        """Test bass cut filter generation."""
        opp = EQOpportunity(
            cut_type=EQCutType.BASS_CUT,
            bar=12,
            confidence=0.90,
            frequency_band=FrequencyBand.LOW,
            magnitude_db=-8.0,
            envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
            phrase_length_bars=4,
            reason="Test bass cut"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        assert "dj_bass_cut" in code
        assert "magnitude_db=-8.0" in code
        assert "freq_hz=60" in code  # Low band default
        assert "start_sec=" in code
        assert "hold_sec=" in code
    
    def test_high_swap_generation(self, dsp_gen):
        """Test high-frequency swap filter generation."""
        opp = EQOpportunity(
            cut_type=EQCutType.HIGH_SWAP,
            bar=8,
            confidence=0.88,
            frequency_band=FrequencyBand.HIGH,
            magnitude_db=-4.5,
            envelope=EQEnvelope(attack_ms=200, hold_bars=4, release_ms=200),
            phrase_length_bars=8,
            reason="Test high swap"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        assert "dj_high_swap" in code
        assert "magnitude_db=-4.5" in code
        assert "freq_hz=3000" in code  # High band default
        assert "attack_sec=0.2" in code  # 200ms
        assert "release_sec=0.2" in code
    
    def test_filter_sweep_generation(self, dsp_gen):
        """Test filter sweep generation."""
        opp = EQOpportunity(
            cut_type=EQCutType.FILTER_SWEEP,
            bar=0,
            confidence=0.92,
            frequency_band=FrequencyBand.SWEEP,
            magnitude_db=-12.0,
            envelope=EQEnvelope(attack_ms=100, hold_bars=12, release_ms=200),
            phrase_length_bars=16,
            reason="Test filter sweep"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        assert "dj_filter_sweep" in code
        assert "start_freq_hz=2000" in code  # Muffled start
        assert "end_freq_hz=20000" in code   # Open end
        assert "attack_sec=0.1" in code
    
    def test_three_band_blend_generation(self, dsp_gen):
        """Test three-band blend filter generation."""
        opp = EQOpportunity(
            cut_type=EQCutType.THREE_BAND_BLEND,
            bar=16,
            confidence=0.85,
            frequency_band=FrequencyBand.LOW,  # Doesn't matter for this type
            magnitude_db=-6.0,
            envelope=EQEnvelope(attack_ms=500, hold_bars=8, release_ms=500),
            phrase_length_bars=16,
            reason="Test three-band blend"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        assert "dj_three_band_blend" in code
        assert "magnitude_db=-6.0" in code
        assert "attack_sec=0.5" in code
        assert "release_sec=0.5" in code
    
    def test_bass_swap_generation(self, dsp_gen):
        """Test bass swap filter generation."""
        opp = EQOpportunity(
            cut_type=EQCutType.BASS_SWAP,
            bar=4,
            confidence=0.75,
            frequency_band=FrequencyBand.LOW,
            magnitude_db=-7.0,
            envelope=EQEnvelope(attack_ms=50, hold_bars=4, release_ms=50),
            phrase_length_bars=4,
            reason="Test bass swap"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        assert "dj_bass_swap" in code
        assert "magnitude_db=-7.0" in code
        assert "freq_hz=60" in code
    
    def test_multiple_opportunities(self, dsp_gen):
        """Test generating code with multiple EQ opportunities."""
        opps = [
            EQOpportunity(
                cut_type=EQCutType.FILTER_SWEEP,
                bar=0,
                confidence=0.92,
                frequency_band=FrequencyBand.SWEEP,
                magnitude_db=-12.0,
                envelope=EQEnvelope(attack_ms=100, hold_bars=12, release_ms=200),
                phrase_length_bars=16,
                reason="Intro sweep"
            ),
            EQOpportunity(
                cut_type=EQCutType.HIGH_SWAP,
                bar=8,
                confidence=0.88,
                frequency_band=FrequencyBand.HIGH,
                magnitude_db=-4.5,
                envelope=EQEnvelope(attack_ms=200, hold_bars=4, release_ms=200),
                phrase_length_bars=8,
                reason="Vocal harshness"
            ),
            EQOpportunity(
                cut_type=EQCutType.BASS_CUT,
                bar=24,
                confidence=0.85,
                frequency_band=FrequencyBand.LOW,
                magnitude_db=-8.0,
                envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
                phrase_length_bars=4,
                reason="Breakdown tension"
            ),
        ]
        
        code = dsp_gen.generate_dsp_chain(opps, 32, "Test Track")
        
        # All three should appear in order
        assert "dj_filter_sweep" in code
        assert "dj_high_swap" in code
        assert "dj_bass_cut" in code
        
        # Check ordering (filter sweep should appear before high swap)
        filter_pos = code.find("dj_filter_sweep")
        high_pos = code.find("dj_high_swap")
        bass_pos = code.find("dj_bass_cut")
        assert filter_pos < high_pos < bass_pos
    
    def test_out_of_bounds_opportunity_rejected(self, dsp_gen):
        """Test that out-of-bounds opportunities are skipped."""
        opp = EQOpportunity(
            cut_type=EQCutType.BASS_CUT,
            bar=40,  # Beyond 32-bar track
            confidence=0.90,
            frequency_band=FrequencyBand.LOW,
            magnitude_db=-8.0,
            envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
            phrase_length_bars=4,
            reason="Out of bounds"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        # Should generate identity (opportunity skipped)
        # Check structure: function definition with identity body
        assert "let eq_dsp = fun(s) ->" in code
        assert "|>" not in code  # No pipes (no filters applied)
    
    def test_opportunity_truncated_at_track_end(self, dsp_gen):
        """Test that opportunities extending past track end are truncated."""
        opp = EQOpportunity(
            cut_type=EQCutType.FILTER_SWEEP,
            bar=24,
            confidence=0.92,
            frequency_band=FrequencyBand.SWEEP,
            magnitude_db=-12.0,
            envelope=EQEnvelope(attack_ms=100, hold_bars=12, release_ms=200),
            phrase_length_bars=16,  # Would extend to bar 40
            reason="Late sweep"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        # Should generate filter sweep (truncated to 8 bars)
        assert "dj_filter_sweep" in code
    
    def test_helpers_template_complete(self, dsp_gen):
        """Test that Liquidsoap helpers template is valid."""
        helpers = dsp_gen.generate_liquidsoap_helpers()
        
        # Should contain all helper function definitions
        assert "dj_bass_cut" in helpers
        assert "dj_high_swap" in helpers
        assert "dj_filter_sweep" in helpers
        assert "dj_three_band_blend" in helpers
        assert "dj_bass_swap" in helpers
        
        # Should contain utility functions
        assert "dj_lerp" in helpers
        assert "dj_envelope_linear" in helpers
        assert "def dj_" in helpers  # Function definitions
    
    def test_bar_to_seconds_conversion(self, dsp_gen):
        """Test bar → seconds conversion."""
        # At 128 BPM, 1 bar = 1.875 seconds
        assert abs(dsp_gen.seconds_per_bar - 1.875) < 0.001
        # 8 bars should be ~15 seconds
        assert abs(8 * dsp_gen.seconds_per_bar - 15.0) < 0.01
    
    def test_magnitude_db_in_range(self, dsp_gen):
        """Test that magnitude dB values stay in expected range."""
        # All magnitudes should be negative (cuts, not boosts)
        test_opps = [
            EQOpportunity(
                cut_type=EQCutType.BASS_CUT,
                bar=0,
                confidence=0.90,
                frequency_band=FrequencyBand.LOW,
                magnitude_db=-8.0,
                envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
                phrase_length_bars=4,
                reason="Test"
            ),
            EQOpportunity(
                cut_type=EQCutType.HIGH_SWAP,
                bar=8,
                confidence=0.88,
                frequency_band=FrequencyBand.HIGH,
                magnitude_db=-4.5,
                envelope=EQEnvelope(attack_ms=200, hold_bars=4, release_ms=200),
                phrase_length_bars=8,
                reason="Test"
            ),
        ]
        
        code = dsp_gen.generate_dsp_chain(test_opps, 32, "Test Track")
        
        # All magnitude_db values should be negative
        assert "magnitude_db=-8.0" in code
        assert "magnitude_db=-4.5" in code


class TestEQAutomationIntegration:
    """Integration tests: detection → DSP code generation."""
    
    def test_detect_and_generate_dsp(self):
        """Test full pipeline: detect opportunities → generate DSP code."""
        # Create detector
        detector = EQAutomationDetector(enabled=True)
        
        # Create engine
        engine = EQAutomationEngine(bpm=128.0)
        
        # Simulate audio features (high confidence for all detections)
        audio_features = {
            'intro_confidence': 0.92,
            'vocal_confidence': 0.88,
            'breakdown_confidence': 0.85,
            'percussiveness': 0.75,
            'num_bars': 32,
            'spectral_centroid': 5000,
            'loudness_db': -10,
            'energy': 0.7,
        }
        
        # Detect opportunities
        opportunities = engine.detect_opportunities(
            audio_features,
            {'artist': 'Test Artist', 'title': 'Test Track'}
        )
        
        assert len(opportunities) > 0
        
        # Generate DSP code
        dsp_gen = EQLiquidsoap(bpm=128.0)
        code = dsp_gen.generate_dsp_chain(opportunities, 32, "Test Artist - Test Track")
        
        # Code should be syntactically valid Liquidsoap
        assert "let eq_dsp = fun(s) ->" in code
        assert "|>" in code  # Pipe operators
        assert "dj_" in code  # Helper functions
    
    def test_detector_disabled(self):
        """Test that detector respects enabled flag."""
        detector = EQAutomationDetector(enabled=False)
        
        audio_features = {
            'intro_confidence': 0.92,
            'vocal_confidence': 0.88,
            'breakdown_confidence': 0.85,
            'percussiveness': 0.75,
            'num_bars': 32,
        }
        
        opportunities = detector.detect_for_track(
            "/path/to/track.mp3",
            128.0,
            audio_features,
            {'artist': 'Test', 'title': 'Track'}
        )
        
        # Should return empty list when disabled
        assert len(opportunities) == 0


class TestLiquidsoapSyntaxValidation:
    """Validates that generated Liquidsoap code is syntactically sound."""
    
    @pytest.fixture
    def dsp_gen(self):
        """Create DSP generator at 128 BPM, 44100 Hz."""
        return EQLiquidsoap(bpm=128.0, sample_rate=44100)
    
    def test_generated_code_has_valid_structure(self):
        """Test that generated code follows Liquidsoap structure."""
        dsp_gen = EQLiquidsoap(bpm=128.0)
        
        opp = EQOpportunity(
            cut_type=EQCutType.BASS_CUT,
            bar=12,
            confidence=0.90,
            frequency_band=FrequencyBand.LOW,
            magnitude_db=-8.0,
            envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
            phrase_length_bars=4,
            reason="Test"
        )
        
        code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        # Basic structure checks
        assert code.count("let eq_dsp = fun(s) ->") == 1  # Exactly one function def
        assert code.count("|>") >= 1  # At least one pipe operator
        assert "s" in code  # Source parameter used
        assert "eq_dsp" in code  # Function returned
    
    def test_helpers_can_be_included(self, dsp_gen):
        """Test that helpers can be prepended to generated code."""
        helpers = dsp_gen.generate_liquidsoap_helpers()
        
        opp = EQOpportunity(
            cut_type=EQCutType.FILTER_SWEEP,
            bar=0,
            confidence=0.92,
            frequency_band=FrequencyBand.SWEEP,
            magnitude_db=-12.0,
            envelope=EQEnvelope(attack_ms=100, hold_bars=12, release_ms=200),
            phrase_length_bars=16,
            reason="Test"
        )
        
        dsp_code = dsp_gen.generate_dsp_chain([opp], 32, "Test Track")
        
        # Combined code should be valid
        combined = f"{helpers}\n\n{dsp_code}"
        
        # Basic validity checks
        assert "dj_filter_sweep" in combined
        assert "let eq_dsp = fun(s) ->" in combined


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
