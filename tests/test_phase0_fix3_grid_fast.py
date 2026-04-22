"""
PHASE 0 FIX #3: Grid Validation - Fast Unit Tests

Minimal tests that don't require heavy audio processing.
"""

import sys
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

import pytest
from autodj.analyze.grid_validator import GridValidator, GridConfidence, create_grid_validator


class TestGridValidator:
    """Test GridValidator initialization and structure."""
    
    def test_creation(self):
        """Test validator creation."""
        v = create_grid_validator({'grid_high_fitness_threshold': 0.80})
        assert v.high_fitness_threshold == 0.80
    
    def test_metrics_init(self):
        """Test metrics are initialized."""
        v = create_grid_validator()
        m = v.get_metrics()
        assert m['total_validations'] == 0


class TestGridConfidence:
    """Test GridConfidence enum."""
    
    def test_enum_values(self):
        """Test confidence enum values."""
        assert GridConfidence.HIGH.value == "high"
        assert GridConfidence.MEDIUM.value == "medium"
        assert GridConfidence.LOW.value == "low"


class TestFitnessCalculation:
    """Test fitness score math."""
    
    def test_weighted_fitness(self):
        """Test weighted fitness calculation."""
        onset, tempo, phase, spectral = 0.9, 0.8, 0.7, 0.6
        fitness = 0.30*onset + 0.30*tempo + 0.20*phase + 0.20*spectral
        assert fitness == pytest.approx(0.77)
    
    def test_threshold_high(self):
        """Test HIGH threshold."""
        v = create_grid_validator()
        assert v.high_fitness_threshold == 0.80
    
    def test_threshold_medium(self):
        """Test MEDIUM threshold."""
        v = create_grid_validator()
        assert v.medium_fitness_threshold == 0.60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
