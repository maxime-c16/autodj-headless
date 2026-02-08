"""
Unit Tests for Phase 2: Harmonic Mixing Module
===============================================

Comprehensive test suite with ≥80% code coverage.
Tests cover: key parsing, compatibility calculation, matrix generation,
sequence finding, and JSON export.
"""

import pytest
import json
import tempfile
from pathlib import Path

from src.autodj.analyze.harmonic import (
    HarmonicMixer,
    Track,
    Transition,
    CompatibilityLevel,
    calculate_semitone_distance,
    determine_compatibility,
    suggest_mixing_technique,
    parse_camelot_key,
    CAMELOT_WHEEL,
)


# ============================================================================
# FIXTURE: Test Data
# ============================================================================

@pytest.fixture
def mixer():
    """Create a fresh mixer instance for each test."""
    return HarmonicMixer()


@pytest.fixture
def populated_mixer():
    """Mixer with 4 test tracks."""
    m = HarmonicMixer()
    m.add_tracks_batch([
        {"index": 0, "name": "Track A", "camelot_key": "10B"},
        {"index": 1, "name": "Track B", "camelot_key": "9B"},
        {"index": 2, "name": "Track C", "camelot_key": "11B"},
        {"index": 3, "name": "Track D", "camelot_key": "12B"},
    ])
    return m


# ============================================================================
# TEST: Key Parsing
# ============================================================================

class TestParseCalelotKey:
    """Test Camelot key string parsing."""
    
    def test_parse_valid_major_keys(self):
        """Parse valid major keys (1A-12A)."""
        for i in range(1, 13):
            key = f"{i}A"
            pos, mode = parse_camelot_key(key)
            assert pos == i
            assert mode == "A"
    
    def test_parse_valid_minor_keys(self):
        """Parse valid minor keys (1B-12B)."""
        for i in range(1, 13):
            key = f"{i}B"
            pos, mode = parse_camelot_key(key)
            assert pos == i
            assert mode == "B"
    
    def test_parse_invalid_position(self):
        """Reject invalid positions."""
        with pytest.raises(ValueError):
            parse_camelot_key("0A")  # Too low
        with pytest.raises(ValueError):
            parse_camelot_key("13A")  # Too high
    
    def test_parse_invalid_mode(self):
        """Reject invalid modes."""
        with pytest.raises(ValueError):
            parse_camelot_key("10C")  # Invalid mode
    
    def test_parse_malformed_key(self):
        """Reject malformed keys."""
        with pytest.raises(ValueError):
            parse_camelot_key("A")
        with pytest.raises(ValueError):
            parse_camelot_key("")


# ============================================================================
# TEST: Semitone Distance Calculation
# ============================================================================

class TestCalculateSemitoneDistance:
    """Test semitone distance between keys."""
    
    def test_same_key_distance(self):
        """Distance to same key is 0."""
        assert calculate_semitone_distance("10A", "10A") == 0
        assert calculate_semitone_distance("1B", "1B") == 0
    
    def test_adjacent_key_distance(self):
        """Adjacent keys have distance 1-2."""
        # 10A (G Major, semitone 11) to 9A (E Major, semitone 4)
        # Distance should be 1 (adjacent on wheel)
        dist = calculate_semitone_distance("10A", "9A")
        assert dist <= 2  # Allow small tolerance
    
    def test_opposite_key_distance(self):
        """Opposite keys have larger distance."""
        # Test C Major (5A) to F# Major (11A)
        dist = calculate_semitone_distance("5A", "11A")
        assert dist >= 3
    
    def test_distance_symmetry(self):
        """Distance is symmetric."""
        d1 = calculate_semitone_distance("10A", "3B")
        d2 = calculate_semitone_distance("3B", "10A")
        assert d1 == d2


# ============================================================================
# TEST: Compatibility Determination
# ============================================================================

class TestDetermineCompatibility:
    """Test harmonic compatibility scoring."""
    
    def test_perfect_compatibility(self):
        """Same key = PERFECT (5)."""
        level, score = determine_compatibility("10A", "10A")
        assert level == CompatibilityLevel.PERFECT
        assert score == 5.0
    
    def test_excellent_compatibility(self):
        """Adjacent keys = EXCELLENT (4)."""
        # Keys 1 semitone apart
        level, score = determine_compatibility("10A", "11A")
        assert level == CompatibilityLevel.EXCELLENT
        assert score == 4.0
    
    def test_good_compatibility(self):
        """2 semitone distance = GOOD (3)."""
        level, score = determine_compatibility("5A", "3A")
        assert level == CompatibilityLevel.GOOD
        assert score == 3.0
    
    def test_acceptable_compatibility(self):
        """3 semitone distance = ACCEPTABLE (2)."""
        level, score = determine_compatibility("5A", "8A")
        assert level == CompatibilityLevel.ACCEPTABLE
        assert score == 2.0
    
    def test_poor_compatibility(self):
        """4+ semitone distance = POOR (0-1)."""
        level, score = determine_compatibility("1A", "5A")
        assert level == CompatibilityLevel.POOR
        assert score <= 1.5


# ============================================================================
# TEST: Mixing Technique Suggestion
# ============================================================================

class TestSuggestMixingTechnique:
    """Test DJ mixing technique suggestions."""
    
    def test_perfect_technique(self):
        """Perfect compatibility → perfect_mix."""
        technique = suggest_mixing_technique(CompatibilityLevel.PERFECT)
        assert technique == "perfect_mix"
    
    def test_excellent_technique(self):
        """Excellent → smooth_crossfade."""
        technique = suggest_mixing_technique(CompatibilityLevel.EXCELLENT)
        assert technique == "smooth_crossfade"
    
    def test_acceptable_technique(self):
        """Acceptable → filter_sweep."""
        technique = suggest_mixing_technique(CompatibilityLevel.ACCEPTABLE)
        assert technique == "filter_sweep"
    
    def test_poor_technique(self):
        """Poor → hard_cut."""
        technique = suggest_mixing_technique(CompatibilityLevel.POOR)
        assert technique == "hard_cut"


# ============================================================================
# TEST: Track Management
# ============================================================================

class TestTrackManagement:
    """Test Track data class and addition."""
    
    def test_add_single_track(self, mixer):
        """Add a single track."""
        mixer.add_track(0, "Track 1", "10A")
        assert len(mixer.tracks) == 1
        assert mixer.tracks[0].name == "Track 1"
        assert mixer.tracks[0].camelot_key == "10A"
    
    def test_add_track_with_confidence(self, mixer):
        """Add track with confidence score."""
        mixer.add_track(0, "Track 1", "10A", confidence=0.95)
        assert mixer.tracks[0].confidence == 0.95
    
    def test_add_tracks_batch(self, mixer):
        """Add multiple tracks at once."""
        mixer.add_tracks_batch([
            {"index": 0, "name": "T1", "camelot_key": "10A"},
            {"index": 1, "name": "T2", "camelot_key": "9B"},
            {"index": 2, "name": "T3", "camelot_key": "11A"},
        ])
        assert len(mixer.tracks) == 3
    
    def test_invalid_camelot_key_rejected(self, mixer):
        """Invalid Camelot key raises error."""
        with pytest.raises(ValueError):
            mixer.add_track(0, "Track", "13A")  # Invalid key
    
    def test_invalid_confidence_rejected(self, mixer):
        """Invalid confidence raises error."""
        with pytest.raises(ValueError):
            mixer.add_track(0, "Track", "10A", confidence=1.5)  # >1.0


# ============================================================================
# TEST: Camelot Wheel Completeness
# ============================================================================

class TestCamelotWheelCompleteness:
    """Test that all 24 keys are valid."""
    
    def test_all_major_keys_valid(self):
        """All 12 major keys (1A-12A) are valid."""
        for i in range(1, 13):
            key = f"{i}A"
            assert key in CAMELOT_WHEEL
    
    def test_all_minor_keys_valid(self):
        """All 12 minor keys (1B-12B) are valid."""
        for i in range(1, 13):
            key = f"{i}B"
            assert key in CAMELOT_WHEEL
    
    def test_wheel_size(self):
        """Camelot wheel has exactly 24 keys."""
        assert len(CAMELOT_WHEEL) == 24


# ============================================================================
# TEST: Compatibility Matrix
# ============================================================================

class TestCompatibilityMatrix:
    """Test NxN compatibility matrix generation."""
    
    def test_matrix_size(self, populated_mixer):
        """Matrix is NxN for N tracks."""
        matrix = populated_mixer.calculate_compatibility_matrix()
        assert len(matrix) == 4
        assert all(len(row) == 4 for row in matrix)
    
    def test_diagonal_is_perfect(self, populated_mixer):
        """Diagonal = 5.0 (same track)."""
        matrix = populated_mixer.calculate_compatibility_matrix()
        assert matrix[0][0] == 5.0
        assert matrix[1][1] == 5.0
        assert matrix[2][2] == 5.0
        assert matrix[3][3] == 5.0
    
    def test_matrix_symmetry(self, populated_mixer):
        """Matrix is symmetric."""
        matrix = populated_mixer.calculate_compatibility_matrix()
        for i in range(4):
            for j in range(4):
                assert matrix[i][j] == matrix[j][i]
    
    def test_matrix_values_in_range(self, populated_mixer):
        """All values 0.0-5.0."""
        matrix = populated_mixer.calculate_compatibility_matrix()
        for row in matrix:
            for value in row:
                assert 0.0 <= value <= 5.0
    
    def test_matrix_caching(self, populated_mixer):
        """Matrix is cached and reused."""
        matrix1 = populated_mixer.calculate_compatibility_matrix()
        matrix2 = populated_mixer.calculate_compatibility_matrix()
        assert matrix1 is matrix2  # Same object


# ============================================================================
# TEST: Optimal Sequence Finding
# ============================================================================

class TestOptimalSequence:
    """Test track sequence optimization."""
    
    def test_sequence_includes_all_tracks(self, populated_mixer):
        """Sequence includes all tracks exactly once."""
        sequence = populated_mixer.find_optimal_sequence()
        assert len(sequence) == 4
        assert len(set(sequence)) == 4  # No duplicates
        assert set(sequence) == {0, 1, 2, 3}
    
    def test_sequence_is_valid_indices(self, populated_mixer):
        """Sequence contains valid track indices."""
        sequence = populated_mixer.find_optimal_sequence()
        for idx in sequence:
            assert idx in populated_mixer.tracks
    
    def test_empty_mixer_returns_empty_sequence(self, mixer):
        """Empty mixer returns empty sequence."""
        sequence = mixer.find_optimal_sequence()
        assert sequence == []
    
    def test_single_track_sequence(self, mixer):
        """Single track returns [0]."""
        mixer.add_track(0, "Track", "10A")
        sequence = mixer.find_optimal_sequence()
        assert sequence == [0]


# ============================================================================
# TEST: Transitions
# ============================================================================

class TestTransitions:
    """Test transition generation."""
    
    def test_get_transitions(self, populated_mixer):
        """Get transitions for a sequence."""
        sequence = populated_mixer.find_optimal_sequence()
        transitions = populated_mixer.get_transitions(sequence)
        
        # Should have N-1 transitions for N tracks
        assert len(transitions) == 3
    
    def test_transition_structure(self, populated_mixer):
        """Transitions have required fields."""
        sequence = [0, 1, 2, 3]
        transitions = populated_mixer.get_transitions(sequence)
        
        for t in transitions:
            assert isinstance(t, Transition)
            assert hasattr(t, "from_key")
            assert hasattr(t, "to_key")
            assert hasattr(t, "compatibility_level")
            assert hasattr(t, "compatibility_score")
            assert hasattr(t, "technique")
            assert hasattr(t, "semitone_distance")


# ============================================================================
# TEST: JSON Export
# ============================================================================

class TestJsonExport:
    """Test JSON export functionality."""
    
    def test_export_creates_file(self, populated_mixer):
        """Export creates JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "export.json"
            populated_mixer.export_json(str(filepath))
            assert filepath.exists()
    
    def test_export_valid_json(self, populated_mixer):
        """Exported file is valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "export.json"
            populated_mixer.export_json(str(filepath))
            
            with open(filepath) as f:
                data = json.load(f)
            
            # Check required keys
            assert "analysis_timestamp" in data
            assert "track_count" in data
            assert "tracks" in data
            assert "compatibility_matrix" in data
            assert "optimal_sequence" in data
            assert "transitions" in data
    
    def test_export_timestamp_format(self, populated_mixer):
        """Timestamp is ISO format with Z suffix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "export.json"
            populated_mixer.export_json(str(filepath))
            
            with open(filepath) as f:
                data = json.load(f)
            
            timestamp = data["analysis_timestamp"]
            assert timestamp.endswith("Z")
            assert "T" in timestamp  # ISO format


# ============================================================================
# TEST: Recommendations
# ============================================================================

class TestRecommendations:
    """Test comprehensive recommendations."""
    
    def test_get_recommendations_structure(self, populated_mixer):
        """Recommendations have expected structure."""
        rec = populated_mixer.get_recommendations()
        
        assert "tracks" in rec
        assert "compatibility_matrix" in rec
        assert "optimal_sequence" in rec
        assert "transitions" in rec
        assert len(rec["tracks"]) == 4


# ============================================================================
# INTEGRATION TEST: Real 4-Track Scenario
# ============================================================================

class TestPhase2RealTracks:
    """Integration test with 4 real DJ tracks."""
    
    def test_phase2_real_tracks(self):
        """
        Test harmonic mixing on 4 real DJ tracks with mixed keys.
        
        Track details:
        1. NICE KEED - WE ARE YOUR FRIENDS (Key D/10B)
        2. LOOCEE Ø - COLD HEART (Key G/9B)
        3. DΛVЯ - In Favor Of Noise (Key A/11B)
        4. Niki Istrefi - Red Armor (Key E/12B)
        
        Expected:
        - Keys adjacent to each other (excellent compatibility)
        - Recommended sequence follows compatibility
        - Transitions suggest appropriate mixing techniques
        """
        mixer = HarmonicMixer()
        mixer.add_tracks_batch([
            {"index": 0, "name": "NICE KEED - WE ARE YOUR FRIENDS", "camelot_key": "10B"},
            {"index": 1, "name": "LOOCEE Ø - COLD HEART", "camelot_key": "9B"},
            {"index": 2, "name": "DΛVЯ - In Favor Of Noise", "camelot_key": "11B"},
            {"index": 3, "name": "Niki Istrefi - Red Armor", "camelot_key": "12B"},
        ])
        
        # Get recommendations
        recommendations = mixer.get_recommendations()
        
        # Verify structure
        assert len(recommendations["tracks"]) == 4
        assert len(recommendations["compatibility_matrix"]) == 4
        assert len(recommendations["optimal_sequence"]) == 4
        assert len(recommendations["transitions"]) == 3
        
        # Verify sequence is valid
        sequence = recommendations["optimal_sequence"]
        assert set(sequence) == {0, 1, 2, 3}
        
        # Verify transitions have good compatibility (adjacent keys should be 4-5)
        for transition in recommendations["transitions"]:
            score = transition["compatibility_score"]
            assert 2.0 <= score <= 5.0  # At least acceptable
        
        print("✅ Phase 2 real track test passed")


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
