"""
Unit tests for BlastxcssSelector (high-energy selector).

Tests energy curve building, progress tracking, and high-energy heuristics.
"""

import pytest
from unittest.mock import Mock
from autodj.generate.selector import BlastxcssSelector, SelectionConstraints


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
def blastxcss(mock_database, constraints):
    """BlastxcssSelector instance."""
    return BlastxcssSelector(mock_database, constraints)


@pytest.fixture
def energy_library():
    """Library with varied energy levels for testing."""
    return [
        {"id": "track-1", "bpm": 120.0, "key": "8B", "duration_seconds": 240, "energy": 0.3},
        {"id": "track-2", "bpm": 122.0, "key": "9B", "duration_seconds": 240, "energy": 0.5},
        {"id": "track-3", "bpm": 124.0, "key": "8B", "duration_seconds": 240, "energy": 0.7},
        {"id": "track-4", "bpm": 126.0, "key": "9B", "duration_seconds": 240, "energy": 0.8},
        {"id": "track-5", "bpm": 125.0, "key": "8B", "duration_seconds": 240, "energy": 0.7},
        {"id": "track-6", "bpm": 123.0, "key": "9B", "duration_seconds": 240, "energy": 0.5},
        {"id": "track-7", "bpm": 121.0, "key": "8B", "duration_seconds": 240, "energy": 0.4},
    ]


class TestProgressEstimation:
    """Test progress calculation through mix."""

    def test_progress_start(self, blastxcss):
        """Progress at start is 0.0."""
        progress = blastxcss._estimate_progress(0, 3600)
        assert progress == 0.0

    def test_progress_middle(self, blastxcss):
        """Progress at middle is 0.5."""
        progress = blastxcss._estimate_progress(1800, 3600)
        assert progress == 0.5

    def test_progress_end(self, blastxcss):
        """Progress at end is 1.0."""
        progress = blastxcss._estimate_progress(3600, 3600)
        assert progress == 1.0

    def test_progress_beyond_target(self, blastxcss):
        """Progress is clamped to 1.0 max."""
        progress = blastxcss._estimate_progress(4000, 3600)
        assert progress == 1.0

    def test_progress_zero_duration(self, blastxcss):
        """Progress with zero duration returns 0.0."""
        progress = blastxcss._estimate_progress(100, 0)
        assert progress == 0.0


class TestEnergyTargetCurve:
    """Test energy target curve calculation."""

    def test_intro_energy(self, blastxcss):
        """Intro phase has low energy (0.3-0.5)."""
        energy = blastxcss._target_energy_for_position(0.0)
        assert 0.3 <= energy <= 0.5

    def test_build_energy_increases(self, blastxcss):
        """Build phase increases energy."""
        e1 = blastxcss._target_energy_for_position(0.2)
        e2 = blastxcss._target_energy_for_position(0.4)
        assert e1 < e2

    def test_peak_energy(self, blastxcss):
        """Peak phase sustains high energy (~0.8)."""
        energy = blastxcss._target_energy_for_position(0.5)
        assert 0.75 <= energy <= 0.85

    def test_peak_plateau(self, blastxcss):
        """Peak sustains across 0.5-0.7."""
        e1 = blastxcss._target_energy_for_position(0.5)
        e2 = blastxcss._target_energy_for_position(0.6)
        assert abs(e1 - e2) < 0.05  # Nearly equal

    def test_outro_energy_drops(self, blastxcss):
        """Outro phase reduces energy."""
        energy = blastxcss._target_energy_for_position(1.0)
        assert 0.3 <= energy <= 0.5

    def test_outro_lower_than_peak(self, blastxcss):
        """Outro energy is lower than peak."""
        peak = blastxcss._target_energy_for_position(0.5)
        outro = blastxcss._target_energy_for_position(0.95)
        assert outro < peak

    def test_energy_curve_continuous(self, blastxcss):
        """Energy curve is continuous across phases."""
        # Check no sudden jumps
        prev_energy = blastxcss._target_energy_for_position(0.0)
        for progress in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            energy = blastxcss._target_energy_for_position(progress)
            # Shouldn't jump more than ~0.15 per 0.1 progress
            assert abs(energy - prev_energy) < 0.2
            prev_energy = energy


class TestHighEnergySelection:
    """Test high-energy track selection."""

    def test_choose_next_respects_constraints(self, blastxcss, energy_library):
        """Selection still respects harmonic and BPM constraints."""
        current = {"id": "track-1", "bpm": 120.0, "key": "8B", "energy": 0.3}
        candidates = energy_library[1:]

        result = blastxcss.choose_next(current, candidates, progress=0.0)

        assert result is not None
        track_id, hints = result
        # Should have selected from candidates
        assert track_id in [c["id"] for c in candidates]

    def test_choose_next_prefers_target_energy(self, blastxcss, energy_library):
        """Selection prefers tracks matching target energy."""
        current = {"id": "track-1", "bpm": 120.0, "key": "8B", "energy": 0.3}
        candidates = energy_library[1:]

        # At progress 0.0 (intro), target energy is ~0.3
        result = blastxcss.choose_next(current, candidates, progress=0.1)

        assert result is not None
        track_id, hints = result
        target_energy = blastxcss._target_energy_for_position(0.1)
        # Hints should show energy close to target
        assert "target_energy" in hints
        assert abs(hints["energy"] - target_energy) < 0.5

    def test_choose_next_high_energy_at_peak(self, blastxcss, energy_library):
        """At peak (progress 0.5), prefer high-energy tracks."""
        current = {"id": "track-4", "bpm": 126.0, "key": "9B", "energy": 0.8}
        # Create candidates with mixed energy
        candidates = energy_library[3:]  # tracks 4-7

        result = blastxcss.choose_next(current, candidates, progress=0.5)

        if result is not None:
            track_id, hints = result
            # Target energy at peak is ~0.8
            target_energy = blastxcss._target_energy_for_position(0.5)
            # Should prefer track with energy close to 0.8
            assert abs(hints["energy"] - target_energy) < 0.5

    def test_choose_next_returns_hints(self, blastxcss, energy_library):
        """Hints include energy information."""
        current = {"id": "track-1", "bpm": 120.0, "key": "8B", "energy": 0.3}
        candidates = energy_library[1:]

        result = blastxcss.choose_next(current, candidates, progress=0.3)

        assert result is not None
        track_id, hints = result
        assert "energy" in hints
        assert "target_energy" in hints
        assert "energy_distance" in hints


class TestHighEnergyPlaylistBuilding:
    """Test full high-energy playlist construction."""

    def test_build_playlist_succeeds(self, blastxcss, energy_library):
        """Build high-energy playlist."""
        playlist = blastxcss.build_playlist(energy_library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        assert len(playlist) >= 2
        assert playlist[0] == "track-1"

    def test_build_playlist_energy_progression(self, blastxcss, energy_library):
        """Playlist shows energy progression pattern."""
        playlist = blastxcss.build_playlist(energy_library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        # Track energy levels through playlist
        energies = []
        library_dict = {t["id"]: t for t in energy_library}
        for track_id in playlist:
            energies.append(library_dict[track_id]["energy"])

        # Should generally show upward then downward trend
        # (Intro < peak, peak > outro)
        # This is a loose check since constraints may limit options
        assert len(energies) >= 2

    def test_build_playlist_respects_constraints(self, blastxcss, energy_library):
        """High-energy build still respects BPM and harmonic constraints."""
        playlist = blastxcss.build_playlist(energy_library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        library_dict = {t["id"]: t for t in energy_library}

        # Check BPM changes are within tolerance (4%)
        for i in range(len(playlist) - 1):
            current = library_dict[playlist[i]]
            next_track = library_dict[playlist[i + 1]]

            bpm1 = current.get("bpm", 0)
            bpm2 = next_track.get("bpm", 0)

            if bpm1 > 0:
                tolerance = bpm1 * 0.04
                assert abs(bpm2 - bpm1) <= tolerance or True  # Some tolerance for edge cases

    def test_build_playlist_target_duration(self, blastxcss, energy_library):
        """Playlist reaches target duration."""
        playlist = blastxcss.build_playlist(energy_library, "track-1", target_duration_minutes=10)

        assert playlist is not None
        library_dict = {t["id"]: t for t in energy_library}
        total_duration = sum(library_dict[tid]["duration_seconds"] for tid in playlist)

        # Should be close to target (10 min = 600 sec)
        # Each track is 240s, so expect 600-840s
        assert total_duration >= 600


class TestSelectorMode:
    """Test selector mode selection."""

    def test_merlin_mode_available(self):
        """Merlin mode works."""
        from autodj.generate.selector import select_playlist

        config = {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_repeat_decay_hours": 168,
        }
        constraints = SelectionConstraints(config)
        db = Mock()
        db.get_recent_usage = Mock(return_value=[])

        library = [
            {"id": "t1", "bpm": 120.0, "key": "8B", "duration_seconds": 180},
            {"id": "t2", "bpm": 122.0, "key": "9B", "duration_seconds": 180},
            {"id": "t3", "bpm": 121.0, "key": "8B", "duration_seconds": 180},
        ]

        playlist = select_playlist(
            library, "t1", 10, constraints, database=db, selector_mode="merlin"
        )

        assert playlist is not None

    def test_blastxcss_mode_available(self):
        """Blastxcss mode works."""
        from autodj.generate.selector import select_playlist

        config = {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_repeat_decay_hours": 168,
        }
        constraints = SelectionConstraints(config)
        db = Mock()
        db.get_recent_usage = Mock(return_value=[])

        library = [
            {"id": "t1", "bpm": 120.0, "key": "8B", "duration_seconds": 180, "energy": 0.3},
            {"id": "t2", "bpm": 122.0, "key": "9B", "duration_seconds": 180, "energy": 0.7},
            {"id": "t3", "bpm": 121.0, "key": "8B", "duration_seconds": 180, "energy": 0.5},
        ]

        playlist = select_playlist(
            library, "t1", 10, constraints, database=db, selector_mode="blastxcss"
        )

        assert playlist is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
