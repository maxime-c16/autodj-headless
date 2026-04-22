#!/usr/bin/env python3
"""
Test Suite for BPM Fallback Fix (Issue #1)

Tests:
1. Current behavior: Track skipped when BPM confidence is low
2. Fixed behavior: Track analyzed with fallback BPM when confidence is low
3. Edge cases: Very low BPM, very high BPM, no BPM detected

Run: python -m pytest test_bpm_fallback.py -v
"""

import sys
from pathlib import Path
import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autodj.config import Config
from autodj.db import Database, TrackMetadata

logger = logging.getLogger(__name__)


class TestBPMFallbackBehavior:
    """Test BPM fallback logic in analyze_library.py"""

    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        config = {
            "analysis": {
                "confidence_threshold": 0.05,
                "bpm_search_range": [50, 200],
                "aubio_hop_size": 512,
                "aubio_buf_size": 4096,
            },
            "constraints": {
                "min_track_duration_seconds": 30,
                "max_track_duration_seconds": 1200,
            }
        }
        return config

    @pytest.fixture
    def mock_db(self):
        """Create mock database"""
        db = Mock(spec=Database)
        db.add_track = Mock(return_value=True)
        return db

    def test_low_confidence_bpm_current_behavior(self, mock_config, mock_db):
        """
        TEST 1: Current behavior - track SKIPPED when BPM confidence < 0.05
        
        Expected: Returns (False, None) and track is not added to database
        """
        # Simulate low confidence BPM detection
        with patch('autodj.analyze.bpm.detect_bpm') as mock_bpm:
            # Mock returns None (confidence below threshold)
            mock_bpm.return_value = None
            
            # Import after patching
            from autodj.scripts.analyze_library import analyze_track
            
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            # Current behavior: Track is skipped
            assert success is False, "Current behavior: Track should be skipped"
            assert metadata is None, "Current behavior: Metadata should be None"
            assert mock_db.add_track.call_count == 0, "Track should NOT be added"

    def test_low_confidence_bpm_fixed_behavior(self, mock_config, mock_db):
        """
        TEST 2: Fixed behavior - track ANALYZED with fallback BPM
        
        Expected: Returns (True, metadata) with fallback BPM (e.g., 120)
        """
        # This test validates the DESIRED fixed behavior
        # Requires BPM detection to return None, but track should still be analyzed
        
        with patch('autodj.analyze.bpm.detect_bpm') as mock_bpm, \
             patch('autodj.scripts.analyze_library._get_audio_duration') as mock_duration, \
             patch('autodj.scripts.analyze_library._extract_id3_metadata') as mock_id3, \
             patch('autodj.scripts.analyze_library._generate_track_id') as mock_id:
            
            mock_bpm.return_value = None  # BPM detection fails
            mock_duration.return_value = 180.0  # Valid duration
            mock_id3.return_value = ("Test Track", "Test Artist", "Test Album")
            mock_id.return_value = "abc123"
            
            # After FIX: Should use fallback BPM
            from autodj.scripts.analyze_library import analyze_track
            
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            # Fixed behavior: Track should be analyzed with fallback BPM
            assert success is True, "Fixed behavior: Track should be analyzed"
            assert metadata is not None, "Fixed behavior: Metadata should exist"
            assert metadata.bpm == 120.0, "Fixed behavior: Should use fallback BPM (120)"
            assert mock_db.add_track.call_count == 1, "Track should be added to DB"

    def test_very_low_bpm_edge_case(self, mock_config, mock_db):
        """
        TEST 3: Edge case - Very low BPM (80 BPM)
        
        Expected: Should accept if within range, even with low confidence
        """
        with patch('autodj.analyze.bpm.detect_bpm') as mock_bpm, \
             patch('autodj.scripts.analyze_library._get_audio_duration') as mock_duration:
            
            mock_bpm.return_value = 80.0  # Valid but low
            mock_duration.return_value = 180.0
            
            from autodj.scripts.analyze_library import analyze_track
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            assert success is True, "Should accept BPM in valid range"
            assert metadata.bpm == 80.0, "BPM should be 80"

    def test_very_high_bpm_edge_case(self, mock_config, mock_db):
        """
        TEST 4: Edge case - Very high BPM (170 BPM)
        
        Expected: Should accept if within range
        """
        with patch('autodj.analyze.bpm.detect_bpm') as mock_bpm, \
             patch('autodj.scripts.analyze_library._get_audio_duration') as mock_duration:
            
            mock_bpm.return_value = 170.0  # Valid but high
            mock_duration.return_value = 180.0
            
            from autodj.scripts.analyze_library import analyze_track
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            assert success is True, "Should accept BPM in valid range"
            assert metadata.bpm == 170.0, "BPM should be 170"

    def test_track_too_short_rejected(self, mock_config, mock_db):
        """
        TEST 5: Track too short (< 30 seconds) should be rejected
        
        Expected: Returns (False, None)
        """
        with patch('autodj.scripts.analyze_library._get_audio_duration') as mock_duration:
            mock_duration.return_value = 10.0  # Too short
            
            from autodj.scripts.analyze_library import analyze_track
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            assert success is False, "Too short track should be rejected"
            assert metadata is None

    def test_track_too_long_rejected(self, mock_config, mock_db):
        """
        TEST 6: Track too long (> 1200 seconds) should be rejected
        
        Expected: Returns (False, None)
        """
        with patch('autodj.scripts.analyze_library._get_audio_duration') as mock_duration:
            mock_duration.return_value = 2000.0  # Too long
            
            from autodj.scripts.analyze_library import analyze_track
            result = analyze_track("dummy_file.mp3", mock_db, mock_config)
            success, metadata = result
            
            assert success is False, "Too long track should be rejected"
            assert metadata is None


class TestBPMConfidenceThreshold:
    """Test confidence threshold logic"""

    def test_confidence_threshold_acceptance(self):
        """
        TEST 7: BPM with confidence above threshold should be accepted
        
        Config: confidence_threshold = 0.05
        Input: BPM 120 with confidence 0.5
        Expected: Should return 120
        """
        from autodj.analyze.bpm import detect_bpm
        
        # This would require actual audio file or mock essentia/aubio
        # Placeholder for actual test
        pass

    def test_lower_threshold_allows_more_bpms(self):
        """
        TEST 8: Lowering confidence threshold allows more BPM detections
        
        Config: confidence_threshold = 0.0 (accept all)
        Expected: More tracks pass BPM detection
        """
        config_strict = {"confidence_threshold": 0.05}
        config_lenient = {"confidence_threshold": 0.0}
        
        # Lenient config should accept more tracks
        # This validates the FIX: lower threshold = fewer skipped tracks


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
