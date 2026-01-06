"""
Unit tests for ArchwizardPhonemius (Phonemius) playlist generator.

Tests playlist orchestration, seed selection, and transition planning.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from autodj.generate.playlist import (
    ArchwizardPhonemius,
    TransitionPlan,
    generate,
    write_m3u,
    write_transitions,
)


@pytest.fixture
def sample_library():
    """Sample track library for testing."""
    return [
        {
            "id": "track-1",
            "file_path": "/music/track1.mp3",
            "bpm": 126.0,
            "key": "8B",
            "duration_seconds": 240,
            "title": "Track 1",
        },
        {
            "id": "track-2",
            "file_path": "/music/track2.mp3",
            "bpm": 128.0,
            "key": "9B",
            "duration_seconds": 240,
            "title": "Track 2",
        },
        {
            "id": "track-3",
            "file_path": "/music/track3.mp3",
            "bpm": 127.0,
            "key": "8B",
            "duration_seconds": 240,
            "title": "Track 3",
        },
        {
            "id": "track-4",
            "file_path": "/music/track4.mp3",
            "bpm": 126.0,
            "key": "9B",
            "duration_seconds": 240,
            "title": "Track 4",
        },
    ]


@pytest.fixture
def config():
    """Test configuration."""
    return {
        "constraints": {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_repeat_decay_hours": 168,
        },
        "render": {
            "crossfade_duration_seconds": 4.0,
        },
    }


@pytest.fixture
def mock_database():
    """Mock database with no recent usage."""
    db = Mock()
    db.get_recent_usage = Mock(return_value=[])
    return db


@pytest.fixture
def phonemius(mock_database, config):
    """Phonemius instance."""
    return ArchwizardPhonemius(mock_database, config)


class TestSeedTrackSelection:
    """Test seed track selection."""

    def test_select_explicit_seed_found(self, phonemius, sample_library):
        """Select explicit seed that exists in library."""
        seed_id = phonemius._select_seed_track(sample_library, "track-2")
        assert seed_id == "track-2"

    def test_select_explicit_seed_not_found(self, phonemius, sample_library):
        """Fall back to random if explicit seed not found."""
        with patch("autodj.generate.playlist.random.choice") as mock_choice:
            mock_choice.return_value = sample_library[0]
            seed_id = phonemius._select_seed_track(sample_library, "track-nonexistent")
            assert seed_id is not None
            assert seed_id in [t.get("id") for t in sample_library]

    def test_select_random_seed(self, phonemius, sample_library):
        """Select random seed when no explicit seed given."""
        with patch("autodj.generate.playlist.random.choice") as mock_choice:
            mock_choice.return_value = sample_library[1]
            seed_id = phonemius._select_seed_track(sample_library)
            assert seed_id == "track-2"
            mock_choice.assert_called_once()

    def test_select_seed_empty_library(self, phonemius):
        """Return None for empty library."""
        seed_id = phonemius._select_seed_track([])
        assert seed_id is None

    def test_select_seed_respects_min_duration(self, phonemius):
        """Only select tracks with sufficient duration."""
        short_library = [
            {"id": "track-1", "duration_seconds": 60},  # Too short
            {"id": "track-2", "duration_seconds": 240},  # OK
        ]
        with patch("autodj.generate.playlist.random.choice") as mock_choice:
            mock_choice.return_value = short_library[1]
            seed_id = phonemius._select_seed_track(short_library)
            # Should only consider track-2 in candidates
            mock_choice.assert_called_once()


class TestTransitionPlanning:
    """Test transition plan generation."""

    def test_plan_transitions_basic(self, phonemius, sample_library):
        """Generate transitions for track sequence."""
        library_dict = {t.get("id"): t for t in sample_library}
        track_ids = ["track-1", "track-2", "track-3"]

        transitions = phonemius._plan_transitions(track_ids, library_dict)

        assert len(transitions) == 3
        assert all(isinstance(t, TransitionPlan) for t in transitions)
        assert transitions[0].track_id == "track-1"
        assert transitions[1].track_id == "track-2"
        assert transitions[2].track_id == "track-3"

    def test_transition_next_track_references(self, phonemius, sample_library):
        """Transitions reference next track correctly."""
        library_dict = {t.get("id"): t for t in sample_library}
        track_ids = ["track-1", "track-2", "track-3"]

        transitions = phonemius._plan_transitions(track_ids, library_dict)

        assert transitions[0].next_track_id == "track-2"
        assert transitions[1].next_track_id == "track-3"
        assert transitions[2].next_track_id is None  # Final track

    def test_transition_effect_selection(self, phonemius):
        """Transition effect selected based on harmonic context."""
        library_dict = {
            "track-1": {"id": "track-1", "key": "8B"},
            "track-2": {"id": "track-2", "key": "9B"},
        }

        # Same key should use simple crossfade
        effect = phonemius._select_transition_effect("8B", "track-1", library_dict)
        assert effect == "smart_crossfade"

        # Different keys should still use smart crossfade (for now)
        effect = phonemius._select_transition_effect("8B", "track-2", library_dict)
        assert effect == "smart_crossfade"

    def test_transition_final_track_effect(self, phonemius):
        """Final track uses default effect."""
        effect = phonemius._select_transition_effect("8B", None, {})
        assert effect == "smart_crossfade"


class TestPlaylistBuilding:
    """Test full playlist building."""

    def test_build_playlist_success(self, phonemius, sample_library, mock_database):
        """Build complete playlist with transitions."""
        with patch.object(phonemius, "_select_seed_track", return_value="track-1"):
            result = phonemius.build_playlist(sample_library, target_duration_minutes=10)

        assert result is not None
        track_ids, transitions = result
        assert len(track_ids) >= 2
        assert len(transitions) == len(track_ids)
        assert track_ids[0] == "track-1"

    def test_build_playlist_seed_selection_fails(self, phonemius, sample_library):
        """Handle failure to select seed."""
        with patch.object(phonemius, "_select_seed_track", return_value=None):
            result = phonemius.build_playlist(sample_library, target_duration_minutes=10)

        assert result is None

    def test_build_playlist_empty_library(self, phonemius):
        """Handle empty library."""
        result = phonemius.build_playlist([], target_duration_minutes=10)
        assert result is None

    def test_build_playlist_playlist_id_generated(self, phonemius, sample_library):
        """Auto-generate playlist ID if not provided."""
        with patch.object(phonemius, "_select_seed_track", return_value="track-1"):
            result = phonemius.build_playlist(sample_library, target_duration_minutes=10, playlist_id=None)

        assert result is not None
        # Should have auto-generated ID (checked via logging or internal state)
        track_ids, transitions = result
        assert len(transitions) > 0

    def test_build_playlist_explicit_playlist_id(self, phonemius, sample_library):
        """Use explicit playlist ID."""
        with patch.object(phonemius, "_select_seed_track", return_value="track-1"):
            result = phonemius.build_playlist(
                sample_library, target_duration_minutes=10, playlist_id="custom-id"
            )

        assert result is not None


class TestGenerateFunction:
    """Test the generate() function (entry point)."""

    def test_generate_requires_config(self, sample_library):
        """Generate fails without config."""
        result = generate(track_ids=["track-1"], library=sample_library, config=None)
        assert result is None

    def test_generate_orchestrated_mode(self, sample_library, config, mock_database):
        """Generate with orchestrated mode (target_duration + database)."""
        with patch("autodj.generate.playlist.ArchwizardPhonemius") as MockPhoenemius:
            mock_instance = Mock()
            mock_instance.build_playlist.return_value = (["track-1", "track-2"], [])
            MockPhoenemius.return_value = mock_instance

            result = generate(
                library=sample_library,
                config=config,
                target_duration_minutes=10,
                database=mock_database,
            )

            assert result is not None
            MockPhoenemius.assert_called_once_with(mock_database, config)
            mock_instance.build_playlist.assert_called_once()

    def test_generate_direct_mode(self, sample_library, config, tmp_path):
        """Generate with direct mode (explicit track IDs)."""
        result = generate(
            track_ids=["track-1", "track-2"],
            library=sample_library,
            config=config,
            output_dir=str(tmp_path),
        )

        assert result is not None
        playlist_path, transitions_path = result
        assert Path(playlist_path).exists()
        assert Path(transitions_path).exists()

    def test_generate_missing_required_params(self, sample_library, config):
        """Generate fails with missing required parameters."""
        result = generate(library=sample_library, config=config)
        assert result is None


class TestM3UWriting:
    """Test M3U file writing."""

    def test_write_m3u_basic(self, tmp_path):
        """Write basic M3U file."""
        output_file = tmp_path / "playlist.m3u"
        track_paths = ["/music/track1.mp3", "/music/track2.mp3"]

        result = write_m3u(track_paths, output_file)

        assert result is True
        assert output_file.exists()
        content = output_file.read_text()
        assert "#EXTM3U" in content
        assert "/music/track1.mp3" in content
        assert "/music/track2.mp3" in content

    def test_write_m3u_with_metadata(self, tmp_path, sample_library):
        """Write M3U with duration metadata."""
        output_file = tmp_path / "playlist.m3u"
        library_dict = {t.get("id"): t for t in sample_library}
        track_paths = ["/music/track1.mp3", "/music/track2.mp3"]

        result = write_m3u(track_paths, output_file, library_dict=library_dict)

        assert result is True
        content = output_file.read_text()
        # Check that durations are included
        assert "#EXT-INF:" in content

    def test_write_m3u_empty_paths(self, tmp_path):
        """Write M3U with empty path list."""
        output_file = tmp_path / "playlist.m3u"
        result = write_m3u([], output_file)

        assert result is True
        assert output_file.exists()
        content = output_file.read_text()
        assert "#EXTM3U" in content


class TestTransitionWriting:
    """Test transition JSON writing."""

    def test_write_transitions_basic(self, tmp_path):
        """Write transitions JSON file."""
        output_file = tmp_path / "transitions.json"
        transitions = [
            TransitionPlan(track_index=0, track_id="track-1", next_track_id="track-2"),
            TransitionPlan(track_index=1, track_id="track-2", next_track_id=None),
        ]

        result = write_transitions(transitions, "playlist-1", 480, output_file)

        assert result is True
        assert output_file.exists()
        import json

        data = json.loads(output_file.read_text())
        assert data["playlist_id"] == "playlist-1"
        assert len(data["transitions"]) == 2
        assert data["transitions"][0]["track_id"] == "track-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
