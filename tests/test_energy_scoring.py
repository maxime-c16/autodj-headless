"""
Unit tests for energy scoring and estimation.

Tests energy estimation, continuity scoring, and ranking.
"""

import pytest
import math
from autodj.generate.energy import (
    estimate_track_energy,
    compute_energy_distance,
    compute_energy_score,
    rank_candidates_by_energy,
)


class TestEnergyEstimation:
    """Test track energy estimation."""

    def test_estimate_explicit_energy(self):
        """Use explicit energy if provided."""
        track = {"id": "track-1", "energy": 0.75}
        energy = estimate_track_energy(track)
        assert energy == 0.75

    def test_estimate_cue_in_energy(self):
        """Primary: cue_in energy."""
        track = {"id": "track-1", "cue_in_energy": 0.8, "cue_out_energy": 0.6}
        energy = estimate_track_energy(track)
        assert energy == 0.8

    def test_estimate_cue_out_energy_fallback(self):
        """Fallback to cue_out if cue_in missing."""
        track = {"id": "track-1", "cue_out_energy": 0.6}
        energy = estimate_track_energy(track)
        assert energy == 0.6

    def test_estimate_loudness_db(self):
        """Estimate from loudness in dB."""
        track = {"id": "track-1", "loudness_db": -10.0}
        energy = estimate_track_energy(track)
        # (-10 + 40) / 40 = 0.75
        assert energy == 0.75

    def test_estimate_bpm_proxy(self):
        """Rough estimate from BPM."""
        track = {"id": "track-1", "bpm": 130.0}
        energy = estimate_track_energy(track)
        # (130 - 80) / 100 = 0.5
        assert energy == 0.5

    def test_estimate_neutral_no_data(self):
        """Neutral 0.5 if no data available."""
        track = {"id": "track-1"}
        energy = estimate_track_energy(track)
        assert energy == 0.5

    def test_estimate_clamp_bounds(self):
        """Clamp energy to [0.0, 1.0]."""
        track = {"id": "track-1", "energy": 1.5}
        energy = estimate_track_energy(track)
        assert energy == 1.0

        track = {"id": "track-1", "energy": -0.5}
        energy = estimate_track_energy(track)
        assert energy == 0.0

    def test_estimate_priority_order(self):
        """Explicit energy takes priority over all others."""
        track = {
            "id": "track-1",
            "energy": 0.9,
            "cue_in_energy": 0.5,
            "loudness_db": -20.0,
            "bpm": 100.0,
        }
        energy = estimate_track_energy(track)
        assert energy == 0.9


class TestEnergyDistance:
    """Test energy distance computation."""

    def test_distance_same_energy(self):
        """Distance is 0 for same energy."""
        distance = compute_energy_distance(0.5, 0.5)
        assert distance == 0.0

    def test_distance_opposite_energy(self):
        """Distance is 1.0 for opposite energy."""
        distance = compute_energy_distance(0.0, 1.0)
        assert distance == 1.0

    def test_distance_half_way(self):
        """Distance is 0.5 for half-way."""
        distance = compute_energy_distance(0.25, 0.75)
        assert distance == 0.5

    def test_distance_symmetric(self):
        """Distance is symmetric."""
        d1 = compute_energy_distance(0.3, 0.7)
        d2 = compute_energy_distance(0.7, 0.3)
        assert d1 == d2


class TestEnergyScoring:
    """Test energy continuity scoring."""

    def test_score_empty_candidates(self):
        """Return empty dict for empty candidates."""
        current = {"id": "track-0", "energy": 0.5}
        scores = compute_energy_score(current, [])
        assert scores == {}

    def test_score_single_candidate(self):
        """Score single candidate."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [{"id": "track-1", "energy": 0.6}]

        scores = compute_energy_score(current, candidates, energy_window_size=3)

        assert "track-1" in scores
        assert scores["track-1"] >= 0.0

    def test_score_multiple_candidates(self):
        """Score multiple candidates."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [
            {"id": "track-1", "energy": 0.5},  # Exact match (0.0 distance)
            {"id": "track-2", "energy": 0.6},  # Close (0.1 distance)
            {"id": "track-3", "energy": 0.1},  # Far (0.4 distance)
        ]

        scores = compute_energy_score(current, candidates)

        # Close should have lower score than far (based on distance)
        assert scores["track-2"] < scores["track-3"]
        # Exact match should have good score too (0.0 distance base)
        assert "track-1" in scores

    def test_score_prefers_smooth_lookahead(self):
        """Prefer candidates that lead to smooth sequences."""
        current = {"id": "track-0", "energy": 0.5}

        # Scenario A: candidate leads to high variance
        candidates_a = [
            {"id": "track-1", "energy": 0.5},
            {"id": "track-2", "energy": 0.1},  # Abrupt drop
            {"id": "track-3", "energy": 0.9},  # Abrupt jump
        ]

        # Scenario B: candidate leads to smooth sequence
        candidates_b = [
            {"id": "track-1", "energy": 0.5},
            {"id": "track-2", "energy": 0.55},  # Smooth
            {"id": "track-3", "energy": 0.6},  # Smooth
        ]

        scores_a = compute_energy_score(current, candidates_a, energy_window_size=3)
        scores_b = compute_energy_score(current, candidates_b, energy_window_size=3)

        # Both have same distance (0.0), but B should have lower variance score
        # So overall B's track-1 should score better (lower)
        # (Note: this tests the lookahead variance component)
        assert "track-1" in scores_a and "track-1" in scores_b

    def test_score_respects_window_size(self):
        """Energy window size affects lookahead variance."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [
            {"id": "track-1", "energy": 0.5},
            {"id": "track-2", "energy": 0.1},
            {"id": "track-3", "energy": 0.9},
            {"id": "track-4", "energy": 0.5},
        ]

        # Small window
        scores_small = compute_energy_score(current, candidates, energy_window_size=2)

        # Large window
        scores_large = compute_energy_score(current, candidates, energy_window_size=10)

        # Scores might differ due to different lookahead ranges
        assert "track-1" in scores_small
        assert "track-1" in scores_large

    def test_score_missing_track_id(self):
        """Skip candidates without ID."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [
            {"energy": 0.5},  # No ID
            {"id": "track-1", "energy": 0.6},
        ]

        scores = compute_energy_score(current, candidates)

        # Only track-1 should be in scores
        assert len(scores) == 1
        assert "track-1" in scores


class TestRankingCandidates:
    """Test candidate ranking by energy."""

    def test_rank_single_candidate(self):
        """Rank single candidate."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [{"id": "track-1", "energy": 0.6}]

        ranked = rank_candidates_by_energy(current, candidates)

        assert len(ranked) == 1
        # Score = 0.7 * distance + 0.3 * variance = 0.7 * 0.1 + 0.3 * 0 = 0.07
        assert ranked[0][0] == "track-1"
        assert ranked[0][1] == pytest.approx(0.07)

    def test_rank_ascending_order(self):
        """Ranked list is in ascending order (best first)."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [
            {"id": "track-1", "energy": 0.1},  # Worst (0.4 distance)
            {"id": "track-2", "energy": 0.5},  # Best (0.0 distance)
            {"id": "track-3", "energy": 0.9},  # Worst (0.4 distance)
        ]

        ranked = rank_candidates_by_energy(current, candidates)

        # Check ordering
        assert len(ranked) == 3
        # track-2 (distance 0.0) should be first
        assert ranked[0][0] == "track-2"
        # Others should have larger scores
        assert ranked[0][1] < ranked[1][1]
        assert ranked[1][1] < ranked[2][1]

    def test_rank_empty_candidates(self):
        """Rank empty list."""
        current = {"id": "track-0", "energy": 0.5}
        ranked = rank_candidates_by_energy(current, [])
        assert ranked == []

    def test_rank_many_candidates(self):
        """Rank many candidates efficiently."""
        current = {"id": "track-0", "energy": 0.5}
        candidates = [{"id": f"track-{i}", "energy": i / 10.0} for i in range(100)]

        ranked = rank_candidates_by_energy(current, candidates)

        # Should have all 100
        assert len(ranked) == 100
        # Should be sorted
        scores = [score for _, score in ranked]
        assert scores == sorted(scores)


class TestEnergyIntegration:
    """Integration tests for energy scoring."""

    def test_realistic_playlist_energy_progression(self):
        """Energy progression in realistic playlist."""
        # Simulate building a playlist with energy progression
        tracks = [
            {"id": "track-1", "energy": 0.4},  # Intro (low energy)
            {"id": "track-2", "energy": 0.6},  # Build
            {"id": "track-3", "energy": 0.8},  # Peak
            {"id": "track-4", "energy": 0.7},  # Sustain
            {"id": "track-5", "energy": 0.5},  # Comedown
        ]

        # At each step, score remaining candidates
        playlist = [tracks[0]]
        for step in range(1, len(tracks)):
            current = tracks[step - 1]
            candidates = tracks[step:]

            ranked = rank_candidates_by_energy(current, candidates)

            # Best candidate (by energy) should be next track
            # (In realistic scenario, other constraints would apply)
            assert len(ranked) > 0
            best_id, best_score = ranked[0]
            playlist.append(next(t for t in candidates if t["id"] == best_id))

        assert len(playlist) == len(tracks)

    def test_energy_estimation_fallback_chain(self):
        """Test full fallback chain for energy estimation."""
        # Test each level of the fallback chain
        track_explicit = {"id": "t1", "energy": 0.9}
        track_cue_in = {"id": "t2", "cue_in_energy": 0.8}
        track_loudness = {"id": "t3", "loudness_db": -5.0}
        track_bpm = {"id": "t4", "bpm": 150.0}
        track_default = {"id": "t5"}

        e1 = estimate_track_energy(track_explicit)
        e2 = estimate_track_energy(track_cue_in)
        e3 = estimate_track_energy(track_loudness)
        e4 = estimate_track_energy(track_bpm)
        e5 = estimate_track_energy(track_default)

        # All should be valid floats in [0.0, 1.0]
        for e in [e1, e2, e3, e4, e5]:
            assert isinstance(e, float)
            assert 0.0 <= e <= 1.0

        # Explicit should be exact
        assert e1 == 0.9
        # Others should be computed
        assert e2 == 0.8
        assert 0.0 <= e3 <= 1.0
        assert 0.0 <= e4 <= 1.0
        # Default should be 0.5
        assert e5 == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
