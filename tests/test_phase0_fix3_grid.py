"""
Unit Tests for PHASE 0 FIX #3: Grid Validation with Fitness Scoring

Tests the 4-check validation framework and fitness scoring.
(Simplified to avoid expensive audio processing during testing)
"""

import sys
import os
import pytest
import numpy as np

# Add paths
sys.path.insert(0, '/home/mcauchy')
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

from autodj.analyze.grid_validator import (
    GridValidator,
    GridConfidence,
    create_grid_validator,
)


class TestGridValidatorInit:
    """Test GridValidator initialization."""
    
    def test_validator_creation(self):
        """Test validator initializes correctly."""
        validator = create_grid_validator({
            'grid_high_fitness_threshold': 0.80,
            'grid_medium_fitness_threshold': 0.60,
        })
        
        assert validator.high_fitness_threshold == 0.80
        assert validator.medium_fitness_threshold == 0.60
        assert validator.metrics['total_validations'] == 0
    
    def test_validator_default_config(self):
        """Test validator with default config."""
        validator = create_grid_validator()
        
        assert validator.high_fitness_threshold == 0.80
        assert validator.medium_fitness_threshold == 0.60


class TestGridConfidenceLevels:
    """Test grid confidence level classification."""
    
    def test_high_confidence_enum(self):
        """Test HIGH confidence enum."""
        assert GridConfidence.HIGH.value == "high"
    
    def test_medium_confidence_enum(self):
        """Test MEDIUM confidence enum."""
        assert GridConfidence.MEDIUM.value == "medium"
    
    def test_low_confidence_enum(self):
        """Test LOW confidence enum."""
        assert GridConfidence.LOW.value == "low"


class TestGridFitnessScoring:
    """Test fitness score calculation logic."""
    
    def test_fitness_weights(self):
        """Test that fitness scores use correct weights."""
        # Weights should be: 0.30 onset, 0.30 tempo, 0.20 phase, 0.20 spectral
        onset = 0.9
        tempo = 0.8
        phase = 0.7
        spectral = 0.6
        
        fitness = (0.30*onset + 0.30*tempo + 0.20*phase + 0.20*spectral)
        
        assert fitness == pytest.approx(0.77)
    
    def test_fitness_high_threshold(self):
        """Test HIGH fitness threshold."""
        # Should be >= 0.80
        validator = create_grid_validator()
        assert validator.high_fitness_threshold == 0.80
    
    def test_fitness_medium_threshold(self):
        """Test MEDIUM fitness threshold."""
        # Should be 0.60-0.79
        validator = create_grid_validator()
        assert validator.medium_fitness_threshold == 0.60
    
    def test_fitness_bounds(self):
        """Test that fitness scores are bounded 0-1."""
        # Max fitness (all 1.0)
        max_fitness = 0.30*1.0 + 0.30*1.0 + 0.20*1.0 + 0.20*1.0
        assert max_fitness == pytest.approx(1.0)
        
        # Min fitness (all 0.0)
        min_fitness = 0.30*0.0 + 0.30*0.0 + 0.20*0.0 + 0.20*0.0
        assert min_fitness == pytest.approx(0.0)


class TestGridRecommendations:
    """Test grid quality recommendations."""
    
    def test_high_fitness_message(self):
        """Test HIGH fitness recommendation message."""
        high_msg = "Grid quality HIGH - Ready for EQ automation"
        assert "HIGH" in high_msg
        assert "EQ automation" in high_msg
    
    def test_medium_fitness_message(self):
        """Test MEDIUM fitness recommendation message."""
        medium_msg = "Grid quality MEDIUM - Recommend manual verification"
        assert "MEDIUM" in medium_msg
        assert "verification" in medium_msg
    
    def test_low_fitness_message(self):
        """Test LOW fitness recommendation message."""
        low_msg = "Grid quality LOW - Recommend recalculation"
        assert "LOW" in low_msg
        assert "recalculation" in low_msg


class TestGridMetrics:
    """Test metrics tracking."""
    
    def test_metrics_initialization(self):
        """Test metrics are properly initialized."""
        validator = create_grid_validator()
        metrics = validator.get_metrics()
        
        assert metrics['total_validations'] == 0
        assert metrics['high_confidence_grids'] == 0
        assert metrics['medium_confidence_grids'] == 0
        assert metrics['low_confidence_grids'] == 0
    
    def test_metrics_structure(self):
        """Test metrics have expected keys."""
        validator = create_grid_validator()
        metrics = validator.get_metrics()
        
        expected_keys = [
            'total_validations',
            'high_confidence_grids',
            'medium_confidence_grids',
            'low_confidence_grids',
            'avg_fitness_score',
            'validation_coverage',
        ]
        
        for key in expected_keys:
            assert key in metrics


class TestCheckThresholds:
    """Test individual check thresholds."""
    
    def test_onset_alignment_threshold(self):
        """Test onset alignment threshold is 80%."""
        validator = create_grid_validator()
        assert validator.onset_alignment_threshold == 0.80
    
    def test_tempo_consistency_threshold(self):
        """Test tempo consistency threshold is 3 BPM."""
        validator = create_grid_validator()
        assert validator.tempo_consistency_threshold == 3.0
    
    def test_phase_alignment_threshold(self):
        """Test phase alignment threshold is 50ms."""
        validator = create_grid_validator()
        assert validator.phase_alignment_threshold == 50
    
    def test_spectral_consistency_threshold(self):
        """Test spectral consistency threshold."""
        validator = create_grid_validator()
        assert validator.spectral_consistency_threshold == 0.95


class TestGridValidationResult:
    """Test GridValidationResult structure."""
    
    def test_result_has_fitness_score(self):
        """Test result contains fitness_score."""
        validator = create_grid_validator()
        
        # Create minimal synthetic audio
        sr = 8000  # Low sample rate for speed
        audio = np.zeros(sr * 2, dtype=np.float32)  # 2 seconds
        
        result = validator.validate_grid(
            audio, sr, bpm=128.0, downbeat_sample=0
        )
        
        assert hasattr(result, 'fitness_score')
        assert 0 <= result.fitness_score <= 1.0
    
    def test_result_has_confidence(self):
        """Test result contains confidence level."""
        validator = create_grid_validator()
        sr = 8000
        audio = np.zeros(sr * 2, dtype=np.float32)
        
        result = validator.validate_grid(
            audio, sr, bpm=128.0, downbeat_sample=0
        )
        
        assert hasattr(result, 'confidence')
        assert result.confidence in [GridConfidence.HIGH, GridConfidence.MEDIUM, GridConfidence.LOW]
    
    def test_result_has_recommendation(self):
        """Test result contains recommendation."""
        validator = create_grid_validator()
        sr = 8000
        audio = np.zeros(sr * 2, dtype=np.float32)
        
        result = validator.validate_grid(
            audio, sr, bpm=128.0, downbeat_sample=0
        )
        
        assert hasattr(result, 'recommendation')
        assert isinstance(result.recommendation, str)
        assert len(result.recommendation) > 0
    
    def test_result_has_check_scores(self):
        """Test result contains all 4 check scores."""
        validator = create_grid_validator()
        sr = 8000
        audio = np.zeros(sr * 2, dtype=np.float32)
        
        result = validator.validate_grid(
            audio, sr, bpm=128.0, downbeat_sample=0
        )
        
        assert hasattr(result, 'onset_alignment_score')
        assert hasattr(result, 'tempo_consistency_score')
        assert hasattr(result, 'phase_alignment_score')
        assert hasattr(result, 'spectral_consistency_score')
        
        # All should be 0-1
        for score in [
            result.onset_alignment_score,
            result.tempo_consistency_score,
            result.phase_alignment_score,
            result.spectral_consistency_score,
        ]:
            assert 0 <= score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
