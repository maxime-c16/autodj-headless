"""
Unit Tests for PHASE 0 FIX #2: BPM Multi-Pass Validation with Octave Error Detection

Tests the 3-pass voting system and octave error detection.
"""

import sys
import os
import pytest
from pathlib import Path

# Add paths
sys.path.insert(0, '/home/mcauchy')
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

from autodj.analyze.bpm_multipass_validator import (
    BPMMultiPassValidator,
    create_multipass_validator,
)


class TestBPMMultiPassValidator:
    """Test suite for BPMMultiPassValidator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = create_multipass_validator({
            'bpm_search_range': [50, 200],
        })
    
    def test_validator_initialization(self):
        """Test validator initializes correctly."""
        assert self.validator.bpm_range == [50, 200]
        assert self.validator.metrics['total_validations'] == 0
    
    def test_unanimous_agreement_detection(self):
        """Test unanimous agreement (all 3 passes close)."""
        # Test with close BPM values
        result = self.validator.validate_bpm_multipass(
            "/tmp/test.wav",
            {},
            detected_bpm=128.0,
            detected_confidence=0.95,
            detection_method="aubio"
        )
        
        # At minimum, should process the input
        assert result.bpm > 0
        assert result.confidence > 0
        assert result.method == "3-pass voting"
    
    def test_bpm_normalization(self):
        """Test BPM normalization to DJ range (85-175)."""
        validator = create_multipass_validator({})
        
        # Test too slow
        normalized = validator._normalize_bpm(60.0)
        assert normalized == 120.0  # Doubled
        
        # Test too fast
        normalized = validator._normalize_bpm(200.0)
        assert normalized == 100.0  # Halved
        
        # Test in range
        normalized = validator._normalize_bpm(130.0)
        assert normalized == 130.0  # No change
    
    def test_votes_agreement_detection(self):
        """Test agreement detection between votes."""
        validator = create_multipass_validator({})
        
        # Close votes should agree (within 2%)
        votes_close = [128.0, 129.0, 127.5]
        assert validator._votes_agree(votes_close, tolerance=0.02) == True
        
        # Far votes should not agree
        votes_far = [128.0, 140.0, 150.0]
        assert validator._votes_agree(votes_far, tolerance=0.02) == False
    
    def test_agreement_level_determination(self):
        """Test agreement level classification."""
        validator = create_multipass_validator({})
        
        # Unanimous (3 votes within 2%)
        votes_unanimous = [128.0, 129.0, 127.5]
        assert validator._determine_agreement(votes_unanimous) == "unanimous"
        
        # Two votes (no 3rd vote)
        votes_two = [128.0, 129.0]
        assert validator._determine_agreement(votes_two) in ["2pass", "2/3"]
        
        # Single vote
        votes_one = [128.0]
        assert validator._determine_agreement(votes_one) == "1/3"
    
    def test_octave_error_detection_double(self):
        """Test detection of octave error (double BPM)."""
        validator = create_multipass_validator({})
        
        # Simulate: actual BPM is 64, but detected as 128
        # Votes would show consensus around 64
        primary_bpm = 128.0
        all_votes = [128.0, 64.0, 64.0]  # Two votes for half
        
        detected, error_type, corrected = validator._detect_octave_error(primary_bpm, all_votes)
        
        # Should detect octave error
        assert detected == True
        assert error_type == "half"
        assert corrected == pytest.approx(64.0)
    
    def test_octave_error_detection_half(self):
        """Test detection of octave error (half BPM)."""
        validator = create_multipass_validator({})
        
        # Simulate: actual BPM is 256, but detected as 128
        # Votes would show consensus around 256
        primary_bpm = 128.0
        all_votes = [128.0, 256.0, 256.0]  # Two votes for double
        
        detected, error_type, corrected = validator._detect_octave_error(primary_bpm, all_votes)
        
        # Should detect octave error
        assert detected == True
        assert error_type == "double"
        assert corrected == pytest.approx(256.0)
    
    def test_no_octave_error(self):
        """Test when no octave error exists."""
        validator = create_multipass_validator({})
        
        # All votes agree on BPM
        primary_bpm = 128.0
        all_votes = [128.0, 128.5, 127.5]
        
        detected, error_type, corrected = validator._detect_octave_error(primary_bpm, all_votes)
        
        # Should not detect octave error
        assert detected == False
        assert error_type is None
        assert corrected is None
    
    def test_metrics_tracking(self):
        """Test metrics tracking across validations."""
        validator = create_multipass_validator({})
        
        # Simulate multiple validations
        # These would normally come from actual audio, so we test with basic calls
        for i in range(5):
            validator.validate_bpm_multipass(
                "/tmp/test.wav",
                {},
                detected_bpm=128.0 + i,
                detected_confidence=0.9,
                detection_method="aubio"
            )
        
        metrics = validator.get_metrics()
        
        assert metrics['total_validations'] == 5
        assert 'avg_confidence' in metrics
        assert metrics['unanimous_agreement'] + metrics['two_pass_agreement'] + metrics['single_pass'] == 5
    
    def test_consistency_check_pass3(self):
        """Test Pass 3 consistency check."""
        validator = create_multipass_validator({})
        
        # BPM in range should return with adjusted confidence
        bpm, conf = validator._pass3_consistency_check(130.0, 0.85)
        
        assert bpm == pytest.approx(130.0)
        assert 0 < conf <= 0.85  # Confidence adjusted


class TestOctaveErrorCorrection:
    """Test octave error detection and correction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = create_multipass_validator({})
    
    def test_octave_error_correction_halves_bpm(self):
        """Test that octave error correction handles half BPM."""
        # Typical scenario: audio detected as 256 BPM but should be 128
        result = self.validator._detect_octave_error(
            primary_bpm=256.0,
            all_votes=[256.0, 128.0, 128.0]  # Majority vote for half
        )
        
        assert result[0] == True  # Error detected
        assert result[1] == "half"  # Error type
        assert result[2] == pytest.approx(128.0)  # Corrected
    
    def test_octave_error_no_false_positives(self):
        """Test that normal BPMs are not flagged as octave errors."""
        result = self.validator._detect_octave_error(
            primary_bpm=128.0,
            all_votes=[128.0, 128.5, 127.5]  # All agree on 128
        )
        
        assert result[0] == False  # No error
        assert result[1] is None


class TestMultiPassAgreement:
    """Test multi-pass agreement logic."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = create_multipass_validator({})
    
    def test_unanimous_agreement_classification(self):
        """Test unanimous agreement is properly classified."""
        votes = [128.0, 128.3, 127.7]  # All within 1%
        agreement = self.validator._determine_agreement(votes)
        
        assert agreement == "unanimous"
    
    def test_partial_agreement_classification(self):
        """Test partial agreement (2 of 3 pass)."""
        votes = [128.0, 128.5, 150.0]  # Two close, one far
        agreement = self.validator._determine_agreement(votes)
        
        assert agreement == "2/3"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
