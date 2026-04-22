"""
Unit Tests for PHASE 0 FIX #1: Confidence Threshold Validation

Tests the graduated 3-tier confidence validation system.
"""

import sys
import os
import pytest
from pathlib import Path

# Add paths
sys.path.insert(0, '/home/mcauchy')
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

from confidence_validator import (
    ConfidenceValidator,
    ConfidenceTier,
    create_confidence_validator,
    batch_validate_confidences,
)


class TestConfidenceValidator:
    """Test suite for ConfidenceValidator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = create_confidence_validator({
            'confidence_high_threshold': 0.90,
            'confidence_medium_threshold': 0.70,
            'enable_logging': False,  # Disable logging for tests
        })
    
    def test_validator_initialization(self):
        """Test validator initializes with correct thresholds."""
        assert self.validator.high_threshold == 0.90
        assert self.validator.medium_threshold == 0.70
        assert self.validator.metrics['total_validations'] == 0
    
    def test_high_confidence_detection(self):
        """Test HIGH confidence detection (0.90+)."""
        result = self.validator.validate_bpm_confidence(128.0, 0.95, "essentia")
        
        assert result.tier == ConfidenceTier.HIGH
        assert result.valid == True
        assert result.requires_validation == False
        assert result.recommendation == "use_directly"
        assert result.metadata['action'] == 'use_directly'
        assert result.metadata['enable_aggressive_eq'] == True
        assert result.metadata['margin_to_high'] == pytest.approx(0.05)
    
    def test_medium_confidence_detection(self):
        """Test MEDIUM confidence detection (0.70-0.89)."""
        result = self.validator.validate_bpm_confidence(130.0, 0.75, "aubio")
        
        assert result.tier == ConfidenceTier.MEDIUM
        assert result.valid == True
        assert result.requires_validation == True
        assert result.recommendation == "use_with_checkpoints"
        assert result.metadata['action'] == 'use_with_checkpoints'
        assert result.metadata['enable_aggressive_eq'] == False
        assert 'required_checks' in result.metadata
    
    def test_low_confidence_detection(self):
        """Test LOW confidence detection (<0.70)."""
        result = self.validator.validate_bpm_confidence(125.0, 0.45, "aubio")
        
        assert result.tier == ConfidenceTier.LOW
        assert result.valid == False
        assert result.requires_validation == False
        assert result.recommendation == "manual_review_or_fallback"
        assert result.metadata['action'] == 'flag_for_review'
        assert result.metadata['enable_aggressive_eq'] == False
    
    def test_edge_case_exactly_high_threshold(self):
        """Test edge case: confidence exactly at high threshold (0.90)."""
        result = self.validator.validate_bpm_confidence(128.0, 0.90, "essentia")
        
        assert result.tier == ConfidenceTier.HIGH
        assert result.valid == True
    
    def test_edge_case_exactly_medium_threshold(self):
        """Test edge case: confidence exactly at medium threshold (0.70)."""
        result = self.validator.validate_bpm_confidence(128.0, 0.70, "aubio")
        
        assert result.tier == ConfidenceTier.MEDIUM
        assert result.valid == True
    
    def test_edge_case_just_below_medium_threshold(self):
        """Test edge case: confidence just below medium threshold (0.69)."""
        result = self.validator.validate_bpm_confidence(128.0, 0.69, "aubio")
        
        assert result.tier == ConfidenceTier.LOW
        assert result.valid == False
    
    def test_invalid_confidence_value(self):
        """Test invalid confidence value (outside 0-1 range)."""
        result = self.validator.validate_bpm_confidence(128.0, 1.5, "aubio")
        
        assert result.valid == False
        assert result.tier == ConfidenceTier.LOW
        assert 'invalid_confidence_value' in result.metadata['error']
    
    def test_invalid_bpm_value_too_low(self):
        """Test invalid BPM value (too low)."""
        result = self.validator.validate_bpm_confidence(30.0, 0.9, "aubio")
        
        assert result.valid == False
        assert 'invalid_bpm_value' in result.metadata['error']
    
    def test_invalid_bpm_value_too_high(self):
        """Test invalid BPM value (too high)."""
        result = self.validator.validate_bpm_confidence(250.0, 0.9, "aubio")
        
        assert result.valid == False
        assert 'invalid_bpm_value' in result.metadata['error']
    
    def test_metrics_tracking(self):
        """Test metrics tracking across multiple validations."""
        # HIGH confidence
        self.validator.validate_bpm_confidence(128.0, 0.95, "essentia")
        # MEDIUM confidence
        self.validator.validate_bpm_confidence(130.0, 0.75, "aubio")
        # LOW confidence
        self.validator.validate_bpm_confidence(125.0, 0.45, "aubio")
        # Another HIGH
        self.validator.validate_bpm_confidence(132.0, 0.92, "tempogram")
        
        metrics = self.validator.get_validation_metrics()
        
        assert metrics['total_validations'] == 4
        assert metrics['high_confidence_count'] == 2
        assert metrics['medium_confidence_count'] == 1
        assert metrics['low_confidence_count'] == 1
        assert metrics['high_confidence_percent'] == 50.0
        assert metrics['medium_confidence_percent'] == 25.0
        assert metrics['low_confidence_percent'] == 25.0
    
    def test_grid_confidence_validation(self):
        """Test grid-specific confidence validation."""
        # HIGH grid fitness
        result_high = self.validator.validate_grid_confidence(0.85, "track1.mp3")
        assert result_high.tier == ConfidenceTier.HIGH
        assert result_high.valid == True
        
        # MEDIUM grid fitness
        result_med = self.validator.validate_grid_confidence(0.70, "track2.mp3")
        assert result_med.tier == ConfidenceTier.MEDIUM
        assert result_med.valid == True
        
        # LOW grid fitness
        result_low = self.validator.validate_grid_confidence(0.55, "track3.mp3")
        assert result_low.tier == ConfidenceTier.LOW
        assert result_low.valid == False
    
    def test_batch_validation(self):
        """Test batch validation of multiple BPM results."""
        bpm_results = [
            (128.0, 0.95, "essentia"),     # HIGH
            (130.0, 0.75, "aubio"),         # MEDIUM
            (125.0, 0.45, "aubio"),         # LOW
            (132.0, 0.90, "tempogram"),     # HIGH
            (127.0, 0.65, "essentia"),      # LOW
        ]
        
        validator = create_confidence_validator()
        validated, metrics = batch_validate_confidences(bpm_results, validator)
        
        assert len(validated) == 5
        assert metrics['total_validations'] == 5
        assert metrics['high_confidence_count'] == 2
        assert metrics['medium_confidence_count'] == 1
        assert metrics['low_confidence_count'] == 2


class TestThresholdValidation:
    """Test threshold validation logic."""
    
    def test_threshold_ordering(self):
        """Test that thresholds must be ordered (medium < high)."""
        with pytest.raises(ValueError):
            ConfidenceValidator({
                'confidence_high_threshold': 0.70,
                'confidence_medium_threshold': 0.90,  # Invalid: must be < high
            })
    
    def test_custom_thresholds(self):
        """Test custom threshold configuration."""
        validator = create_confidence_validator({
            'confidence_high_threshold': 0.85,
            'confidence_medium_threshold': 0.65,
        })
        
        assert validator.high_threshold == 0.85
        assert validator.medium_threshold == 0.65
        
        # Test with custom thresholds
        high_result = validator.validate_bpm_confidence(128.0, 0.85, "aubio")
        assert high_result.tier == ConfidenceTier.HIGH
        
        med_result = validator.validate_bpm_confidence(128.0, 0.65, "aubio")
        assert med_result.tier == ConfidenceTier.MEDIUM


class TestRecommendationLogic:
    """Test recommendation generation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = create_confidence_validator()
    
    def test_high_confidence_action(self):
        """Test HIGH confidence recommendation."""
        result = self.validator.validate_bpm_confidence(128.0, 0.95, "essentia")
        action = self.validator.get_recommendation_action(result)
        
        assert action == "use_directly"
    
    def test_medium_confidence_action(self):
        """Test MEDIUM confidence recommendation."""
        result = self.validator.validate_bpm_confidence(130.0, 0.75, "aubio")
        action = self.validator.get_recommendation_action(result)
        
        assert action == "use_with_checkpoints"
    
    def test_low_confidence_action(self):
        """Test LOW confidence recommendation."""
        result = self.validator.validate_bpm_confidence(125.0, 0.45, "aubio")
        action = self.validator.get_recommendation_action(result)
        
        assert action == "flag_for_review"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
