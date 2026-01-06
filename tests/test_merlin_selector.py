"""
Unit tests for MerlinGreedySelector (Merlin).

Tests harmonic matching, BPM tolerance, and greedy selection behavior.
"""

import pytest
from unittest.mock import Mock, MagicMock
from autodj.generate.selector import (
    MerlinGreedySelector,
    SelectionConstraints,
    select_playlist,
)


@pytest.fixture
def constraints():
    """Default constraints for testing."""
    config = {
        "bpm_tolerance_percent": 4.0,
        "energy_window_size": 3,
        "min_track_duration_seconds": 120,
        "max_repeat_decay_hours": 168,
    }
    return SelectionConstraints(config)


@pytest.fixture
def mock_database():
    """Mock database with no recent usage."""
    db = Mock()
    db.get_recent_usage = Mock(return_value=[])
    return db


@pytest.fixture
def selector(mock_database, constraints):
    """Merlin selector instance."""
    return MerlinGreedySelector(mock_database, constraints)


class TestCamelotCompatibility:
    """Test harmonic key compatibility checking."""

    def test_exact_key_match(self, selector):
        """Same key is compatible."""
        assert selector._camelot_compatible("8B", "8B") is True

    def test_adjacent_keys_major(self, selector):
        """Adjacent keys on major side are compatible."""
        assert selector._camelot_compatible("8B", "9B") is True
        assert selector._camelot_compatible("9B", "8B") is True

    def test_adjacent_keys_minor(self, selector):
        """Adjacent keys on minor side are compatible."""
        assert selector._camelot_compatible("8A", "9A") is True
        assert selector._camelot_compatible("9A", "8A") is True

    def test_parallel_keys(self, selector):
        """Parallel keys (same number, different mode) are compatible."""
        assert selector._camelot_compatible("8B", "8A") is True
        assert selector._camelot_compatible("8A", "8B") is True

    def test_wheel_wraparound(self, selector):
        """Keys at wheel boundary (12/1) are compatible."""
        assert selector._camelot_compatible("12B", "1B") is True
        assert selector._camelot_compatible("1B", "12B") is True

    def test_incompatible_keys(self, selector):
        """Keys 2 steps apart are incompatible."""
        assert selector._camelot_compatible("8B", "10B") is False
        assert selector._camelot_compatible("8B", "6B") is False

    def test_unknown_key_compatible(self, selector):
        """Unknown keys are always compatible."""
        assert selector._camelot_compatible("unknown", "8B") is True
        assert selector._camelot_compatible("8B", "unknown") is True
        assert selector._camelot_compatible("unknown", "unknown") is True

    def test_none_key_compatible(self, selector):
        """None keys are always compatible."""
        assert selector._camelot_compatible(None, "8B") is True
        assert selector._camelot_compatible("8B", None) is True

    def test_malformed_key(self, selector):
        """Malformed keys are treated as compatible (error-tolerant)."""
        assert selector._camelot_compatible("invalid", "8B") is True
        assert selector._camelot_compatible("8B", "invalid") is True


class TestBPMCompatibility:
    """Test BPM tolerance checking."""

    def test_exact_bpm_match(self, selector):
        """Same BPM is always compatible."""
        assert selector._bpm_compatible(126.0, 126.0, 4.0) is True

    def test_within_tolerance_percent(self, selector):
        """BPM within tolerance percentage is compatible."""
        # At 126 BPM ±4% = ±5.04 BPM
        assert selector._bpm_compatible(126.0, 130.0, 4.0) is True  # +4 BPM
        assert selector._bpm_compatible(126.0, 122.0, 4.0) is True  # -4 BPM

    def test_outside_tolerance_percent(self, selector):
        """BPM outside tolerance percentage is incompatible."""
        # At 126 BPM ±4% = ±5.04 BPM
        assert selector._bpm_compatible(126.0, 132.0, 4.0) is False  # +6 BPM
        assert selector._bpm_compatible(126.0, 120.0, 4.0) is False  # -6 BPM

    def test_zero_tolerance(self, selector):
        """With zero tolerance, only exact match works."""
        assert selector._bpm_compatible(126.0, 126.0, 0.0) is True
        assert selector._bpm_compatible(126.0, 126.1, 0.0) is False

    def test_none_bpm_compatible(self, selector):
        """None BPM is always compatible."""
        assert selector._bpm_compatible(None, 126.0, 4.0) is True
        assert selector._bpm_compatible(126.0, None, 4.0) is True

    def test_low_bpm_tolerance(self, selector):
        """Test tolerance on low BPM."""
        # At 80 BPM ±5% = ±4 BPM = [76, 84]
        assert selector._bpm_compatible(80.0, 83.0, 5.0) is True
        assert selector._bpm_compatible(80.0, 85.0, 5.0) is False


class TestGreedySelection:
    """Test greedy selection logic."""

    def test_choose_next_valid_candidate(self, selector):
        """Selector chooses valid candidate."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 128.0, "key": "9B", "duration_seconds": 180},
        ]

        result = selector.choose_next(current, candidates)

        assert result is not None
        track_id, hints = result
        assert track_id == "track-2"
        assert hints["bpm"] == 128.0
        assert hints["key"] == "9B"

    def test_choose_next_no_candidates(self, selector):
        """Selector returns None when no valid candidates."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = []

        result = selector.choose_next(current, candidates)

        assert result is None

    def test_choose_next_skip_used_in_set(self, selector):
        """Selector skips tracks already used in current set."""
        selector.used_in_set.add("track-2")
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 128.0, "key": "9B"},
        ]

        result = selector.choose_next(current, candidates)

        assert result is None

    def test_choose_next_bpm_incompatible(self, selector):
        """Selector skips candidates with incompatible BPM."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 135.0, "key": "8B"},  # Too fast
        ]

        result = selector.choose_next(current, candidates)

        assert result is None

    def test_choose_next_key_incompatible(self, selector):
        """Selector skips candidates with incompatible key."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 126.0, "key": "10B"},  # 2 steps away
        ]

        result = selector.choose_next(current, candidates)

        assert result is None

    def test_choose_next_multiple_valid_chooses_first(self, selector):
        """With multiple valid candidates, selector chooses first."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 128.0, "key": "9B"},
            {"id": "track-3", "bpm": 127.0, "key": "8B"},
            {"id": "track-4", "bpm": 125.0, "key": "7B"},
        ]

        result = selector.choose_next(current, candidates)

        assert result is not None
        track_id, _ = result
        assert track_id == "track-2"  # First valid candidate

    def test_choose_next_marks_used(self, selector):
        """Selector marks chosen track as used in set."""
        current = {"id": "track-1", "bpm": 126.0, "key": "8B"}
        candidates = [
            {"id": "track-2", "bpm": 128.0, "key": "9B"},
        ]

        result = selector.choose_next(current, candidates)

        assert result is not None
        track_id, _ = result
        assert track_id in selector.used_in_set


class TestPlaylistBuilding:
    """Test full playlist generation."""

    def test_build_playlist_basic(self, selector):
        """Build simple playlist from seed."""
        library = [
            {"id": "track-1", "bpm": 126.0, "key": "8B", "duration_seconds": 180},
            {"id": "track-2", "bpm": 128.0, "key": "9B", "duration_seconds": 180},
            {"id": "track-3", "bpm": 127.0, "key": "8B", "duration_seconds": 180},
        ]

        playlist = selector.build_playlist(library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        assert playlist[0] == "track-1"  # Seed track first
        assert len(playlist) >= 2  # At least seed + one more

    def test_build_playlist_seed_not_found(self, selector):
        """Build fails if seed track not in library."""
        library = [
            {"id": "track-1", "bpm": 126.0, "key": "8B", "duration_seconds": 180},
        ]

        playlist = selector.build_playlist(library, "track-nonexistent", target_duration_minutes=10)

        assert playlist is None

    def test_build_playlist_reaches_target_duration(self, selector):
        """Playlist building stops when target duration reached."""
        library = [
            {"id": "track-1", "bpm": 126.0, "key": "8B", "duration_seconds": 180},
            {"id": "track-2", "bpm": 128.0, "key": "9B", "duration_seconds": 180},
            {"id": "track-3", "bpm": 127.0, "key": "8B", "duration_seconds": 180},
            {"id": "track-4", "bpm": 126.0, "key": "9B", "duration_seconds": 180},
        ]

        playlist = selector.build_playlist(library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        total_duration = sum(
            t["duration_seconds"] for t in library if t["id"] in playlist
        )
        assert total_duration >= 10 * 60  # At least target duration

    def test_build_playlist_respects_max_tracks(self, selector):
        """Playlist respects max_tracks limit."""
        library = [
            {"id": f"track-{i}", "bpm": 126.0, "key": "8B", "duration_seconds": 60}
            for i in range(200)
        ]

        playlist = selector.build_playlist(library, "track-0", target_duration_minutes=60, max_tracks=5)

        assert len(playlist) <= 5

    def test_build_playlist_deterministic(self, selector):
        """Playlist is deterministic (same seed, same result)."""
        library = [
            {"id": "track-1", "bpm": 126.0, "key": "8B", "duration_seconds": 180},
            {"id": "track-2", "bpm": 128.0, "key": "9B", "duration_seconds": 180},
            {"id": "track-3", "bpm": 127.0, "key": "8B", "duration_seconds": 180},
        ]

        # Build twice with same seed
        selector1 = MerlinGreedySelector(self.mock_database, selector.constraints)
        playlist1 = selector1.build_playlist(library, "track-1", target_duration_minutes=10)

        selector2 = MerlinGreedySelector(self.mock_database, selector.constraints)
        playlist2 = selector2.build_playlist(library, "track-1", target_duration_minutes=10)

        assert playlist1 == playlist2

    @pytest.fixture
    def mock_database(self):
        """Mock database."""
        db = Mock()
        db.get_recent_usage = Mock(return_value=[])
        return db


class TestSelectPlaylistFunction:
    """Test the top-level select_playlist function."""

    def test_select_playlist_integration(self):
        """Integration test of select_playlist function."""
        config = {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_repeat_decay_hours": 168,
        }
        constraints = SelectionConstraints(config)

        library = [
            {"id": "track-1", "bpm": 126.0, "key": "8B", "duration_seconds": 180},
            {"id": "track-2", "bpm": 128.0, "key": "9B", "duration_seconds": 180},
            {"id": "track-3", "bpm": 127.0, "key": "8B", "duration_seconds": 180},
        ]

        mock_db = Mock()
        mock_db.get_recent_usage = Mock(return_value=[])

        playlist = select_playlist(library, "track-1", 10, constraints, database=mock_db)

        assert playlist is not None
        assert playlist[0] == "track-1"


class TestRecentUsageCheck:
    """Test repeat decay (recent usage) checking."""

    def test_is_recently_used_true(self, selector, mock_database):
        """Track with recent usage is flagged."""
        mock_database.get_recent_usage.return_value = [
            {"playlist_id": "playlist-1", "position": 0, "used_at": "2024-01-01T00:00:00"},
        ]

        result = selector._is_recently_used("track-1", 168)

        assert result is True

    def test_is_recently_used_false(self, selector, mock_database):
        """Track without recent usage is not flagged."""
        mock_database.get_recent_usage.return_value = []

        result = selector._is_recently_used("track-1", 168)

        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
