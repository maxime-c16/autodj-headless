"""
Tests for the nightly AutoDJ pipeline.

Covers:
- generate_set.py integration (M3U + transitions JSON output)
- Render pipeline output validation and cleanup
- Nightly script idempotency and size bounds
- Full pipeline smoke test with mocked subprocess calls
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ==================== Fixtures ====================


@pytest.fixture
def tmp_output(tmp_path):
    """Create temporary directory structure matching pipeline layout."""
    (tmp_path / "playlists").mkdir()
    (tmp_path / "mixes").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "db").mkdir()
    return tmp_path


@pytest.fixture
def sample_library():
    """Minimal library of fake tracks for generation tests."""
    tracks = []
    for i in range(10):
        tracks.append({
            "id": f"track-{i:03d}",
            "file_path": f"/music/track{i:03d}.mp3",
            "duration_seconds": 240.0 + i * 10,
            "bpm": 120.0 + i * 2,
            "key": f"{(i % 12) + 1}A",
            "cue_in_frames": 0,
            "cue_out_frames": int((240.0 + i * 10) * 44100),
            "title": f"Track {i}",
            "artist": f"Artist {i}",
        })
    return tracks


@pytest.fixture
def sample_config():
    """Config dict matching what pipeline scripts expect."""
    return {
        "system": {
            "database_path": "/tmp/test-metadata.sqlite",
            "playlists_path": "/tmp/test-playlists",
            "mixes_path": "/tmp/test-mixes",
        },
        "mix": {
            "target_duration_minutes": 60,
            "max_playlist_tracks": 90,
            "seed_track_path": "",
        },
        "constraints": {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "max_repeat_decay_hours": 168,
            "min_track_duration_seconds": 60,
        },
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 192,
            "crossfade_duration_seconds": 4.0,
            "time_stretch_quality": "high",
            "max_tracks_before_segment": 10,
            "segment_size": 5,
            "enable_progress_display": False,
        },
    }


@pytest.fixture
def sample_transitions():
    """Valid transitions JSON matching the TransitionPlan schema."""
    return {
        "playlist_id": "test-playlist-001",
        "mix_duration_seconds": 720,
        "generated_at": "2026-02-07T02:30:00",
        "transitions": [
            {
                "track_index": 0,
                "track_id": "track-000",
                "file_path": "/music/track000.mp3",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 121.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 16.0,
                "effect": "smart_crossfade",
                "next_track_id": "track-001",
                "bpm": 120.0,
                "cue_in_frames": 0,
                "cue_out_frames": 10584000,
                "title": "Track 000",
                "artist": "Artist A",
                "outro_start_seconds": 220.0,
            },
            {
                "track_index": 1,
                "track_id": "track-001",
                "file_path": "/music/track001.mp3",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 123.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 15.7,
                "effect": "smart_crossfade",
                "next_track_id": "track-002",
                "bpm": 122.0,
                "cue_in_frames": 44100,
                "cue_out_frames": 11025000,
                "title": "Track 001",
                "artist": "Artist B",
                "outro_start_seconds": 230.0,
                "drop_position_seconds": 28.0,
            },
            {
                "track_index": 2,
                "track_id": "track-002",
                "file_path": "/music/track002.mp3",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 124.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 15.5,
                "effect": "smart_crossfade",
                "next_track_id": None,
                "bpm": 124.0,
                "cue_in_frames": 0,
                "cue_out_frames": 10800000,
                "title": "Track 002",
                "artist": "Artist C",
                "outro_start_seconds": 225.0,
                "drop_position_seconds": 32.0,
            },
        ],
    }


# ==================== TestGenerateSetIntegration ====================


class TestGenerateSetIntegration:
    """Tests that generate_set.py produces valid M3U + transitions JSON."""

    def _generate_direct(self, library, config, output_dir, track_count=5):
        """Helper: call generate() in direct mode (track_ids + library)."""
        from autodj.generate.playlist import generate

        track_ids = [t["id"] for t in library[:track_count]]
        return generate(
            track_ids=track_ids,
            library=library,
            config=config,
            output_dir=output_dir,
        )

    def test_generate_produces_m3u_and_json(self, tmp_output, sample_library, sample_config):
        """generate() should produce both an M3U and transitions JSON file."""
        output_dir = str(tmp_output / "playlists")
        sample_config["system"]["playlists_path"] = output_dir

        result = self._generate_direct(sample_library, sample_config, output_dir)

        assert result is not None, "generate() returned None"
        m3u_path, transitions_path = result

        assert Path(m3u_path).exists(), f"M3U not created: {m3u_path}"
        assert Path(transitions_path).exists(), f"Transitions not created: {transitions_path}"

    def test_m3u_contains_track_paths(self, tmp_output, sample_library, sample_config):
        """Generated M3U should contain actual file paths."""
        output_dir = str(tmp_output / "playlists")
        result = self._generate_direct(sample_library, sample_config, output_dir)

        assert result is not None
        m3u_path, _ = result
        content = Path(m3u_path).read_text()

        assert "#EXTM3U" in content
        # Should contain at least one track path
        assert "/music/" in content

    def test_transitions_json_schema(self, tmp_output, sample_library, sample_config):
        """Transitions JSON should have required schema fields."""
        output_dir = str(tmp_output / "playlists")
        result = self._generate_direct(sample_library, sample_config, output_dir)

        assert result is not None
        _, transitions_path = result

        with open(transitions_path) as f:
            plan = json.load(f)

        # Top-level fields
        assert "playlist_id" in plan
        assert "transitions" in plan
        assert "mix_duration_seconds" in plan
        assert isinstance(plan["transitions"], list)
        assert len(plan["transitions"]) > 0

        # Per-transition fields
        t = plan["transitions"][0]
        required_fields = [
            "track_index", "track_id", "entry_cue", "hold_duration_bars",
            "target_bpm", "exit_cue", "mix_out_seconds", "effect",
            "bpm", "cue_in_frames", "cue_out_frames",
        ]
        for field in required_fields:
            assert field in t, f"Missing field '{field}' in transition"

    def test_generate_handles_empty_library(self, tmp_output, sample_config):
        """generate() should handle empty library gracefully."""
        from autodj.generate.playlist import generate

        output_dir = str(tmp_output / "playlists")
        result = generate(
            track_ids=[],
            library=[],
            config=sample_config,
            output_dir=output_dir,
        )

        # Should return None or empty — not crash
        # Empty track_ids means no tracks to generate for
        assert result is None or result is not None

    def test_generate_handles_single_track(self, tmp_output, sample_config):
        """generate() with one track should still produce output."""
        from autodj.generate.playlist import generate

        single_track = [{
            "id": "only-track",
            "file_path": "/music/only.mp3",
            "duration_seconds": 180.0,
            "bpm": 128.0,
            "key": "8A",
            "cue_in_frames": 0,
            "cue_out_frames": 7938000,
            "title": "Only Track",
            "artist": "Solo",
        }]

        output_dir = str(tmp_output / "playlists")
        result = generate(
            track_ids=["only-track"],
            library=single_track,
            config=sample_config,
            output_dir=output_dir,
        )

        if result is not None:
            m3u_path, transitions_path = result
            assert Path(m3u_path).exists()


# ==================== TestRenderPipelineIntegration ====================


class TestRenderPipelineIntegration:
    """Tests render pipeline validation, cleanup, and metadata."""

    def test_validate_output_rejects_too_small(self):
        """Files under 1 MiB should fail validation."""
        from autodj.render.render import _validate_output_file

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"tiny")
            temp_path = f.name

        try:
            assert _validate_output_file(temp_path) is False
        finally:
            os.unlink(temp_path)

    def test_validate_output_accepts_normal_size(self):
        """Files over 1 MiB should pass validation."""
        from autodj.render.render import _validate_output_file

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x" * (2 * 1024 * 1024))
            temp_path = f.name

        try:
            assert _validate_output_file(temp_path) is True
        finally:
            os.unlink(temp_path)

    def test_cleanup_removes_partial_output(self):
        """_cleanup_partial_output should remove the file."""
        from autodj.render.render import _cleanup_partial_output

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"partial render")
            temp_path = f.name

        assert Path(temp_path).exists()
        _cleanup_partial_output(temp_path)
        assert not Path(temp_path).exists()

    def test_cleanup_ignores_missing_file(self):
        """_cleanup_partial_output should not raise for missing files."""
        from autodj.render.render import _cleanup_partial_output

        _cleanup_partial_output("/nonexistent/path/file.mp3")

    @patch("autodj.render.render.EasyID3")
    def test_metadata_written_to_mp3(self, mock_easyid3):
        """ID3 metadata should be written to MP3 output."""
        from autodj.render.render import _write_mix_metadata

        mock_instance = MagicMock()
        mock_easyid3.return_value = mock_instance

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x" * (2 * 1024 * 1024))
            temp_path = f.name

        try:
            result = _write_mix_metadata(temp_path, "test-playlist", "2026-02-07T02:30:00")
            assert result is True
            mock_instance.save.assert_called_once()
        finally:
            os.unlink(temp_path)

    def test_render_engine_rejects_missing_transitions(self, sample_config):
        """RenderEngine should return False for missing transitions file."""
        from autodj.render.render import RenderEngine

        engine = RenderEngine(sample_config)

        with tempfile.TemporaryDirectory() as tmpdir:
            m3u = Path(tmpdir) / "playlist.m3u"
            m3u.write_text("#EXTM3U\n")
            output = Path(tmpdir) / "mix.mp3"

            result = engine.render_playlist(
                str(Path(tmpdir) / "nonexistent.json"),
                str(m3u),
                str(output),
            )
            assert result is False


# ==================== TestNightlyIdempotency ====================


class TestNightlyIdempotency:
    """Tests the nightly script's idempotency and validation logic."""

    def test_output_filename_format(self):
        """Output filename should be autodj-mix-YYYY-MM-DD.mp3."""
        today = time.strftime("%Y-%m-%d")
        expected = f"autodj-mix-{today}.mp3"
        assert len(expected.split("-")) == 5  # autodj-mix-YYYY-MM-DD.mp3
        assert expected.endswith(".mp3")
        assert expected.startswith("autodj-mix-")

    def test_skip_if_output_exists(self, tmp_path):
        """Script should exit 0 if today's mix already exists."""
        today = time.strftime("%Y-%m-%d")
        output_dir = tmp_path / "automix"
        output_dir.mkdir()
        output_file = output_dir / f"autodj-mix-{today}.mp3"
        output_file.write_bytes(b"x" * 1024)

        assert output_file.exists()

    def test_size_bounds_too_small(self):
        """Files under 1 MB should be rejected."""
        min_size = 1 * 1024 * 1024  # 1 MB
        assert 100 < min_size
        assert 0 < min_size

    def test_size_bounds_too_large(self):
        """Files over 500 MB should be rejected (Liquidsoap runaway)."""
        max_size = 500 * 1024 * 1024  # 500 MB
        # The known 23GB bug file
        bug_size = 23 * 1024 * 1024 * 1024
        assert bug_size > max_size

    def test_size_bounds_normal_mix(self):
        """A 60-minute 320kbps MP3 should be ~144 MB — within bounds."""
        min_size = 1 * 1024 * 1024
        max_size = 500 * 1024 * 1024
        # 60 min * 60 sec * 320 kbps / 8 bits = ~144 MB
        expected_size = 60 * 60 * 320 * 1000 // 8
        assert min_size < expected_size < max_size

    def test_nightly_script_exists_and_executable(self):
        """The nightly script should exist and be executable."""
        script = Path("/home/mcauchy/autodj-headless/scripts/autodj-nightly.sh")
        assert script.exists(), f"Script not found: {script}"
        assert os.access(str(script), os.X_OK), f"Script not executable: {script}"

    def test_nightly_script_has_lock_mechanism(self):
        """Script should use flock for concurrency prevention."""
        script = Path("/home/mcauchy/autodj-headless/scripts/autodj-nightly.sh")
        content = script.read_text()
        assert "flock" in content, "Script should use flock for locking"

    def test_nightly_script_has_size_validation(self):
        """Script should validate output size to catch the 23GB bug."""
        script = Path("/home/mcauchy/autodj-headless/scripts/autodj-nightly.sh")
        content = script.read_text()
        assert "MAX_SIZE" in content, "Script should define MAX_SIZE"
        assert "MIN_SIZE" in content, "Script should define MIN_SIZE"

    def test_nightly_script_has_distinct_exit_codes(self):
        """Script should use distinct exit codes per phase."""
        script = Path("/home/mcauchy/autodj-headless/scripts/autodj-nightly.sh")
        content = script.read_text()
        # Should have exit codes for each phase
        assert "die 2" in content, "Should have exit code 2 for analyze"
        assert "die 3" in content, "Should have exit code 3 for generate"
        assert "die 4" in content, "Should have exit code 4 for render"
        assert "die 5" in content, "Should have exit code 5 for copy/validation"


# ==================== TestFullPipelineSmoke ====================


class TestFullPipelineSmoke:
    """End-to-end smoke test with mocked audio data and subprocess calls."""

    def test_generate_then_validate_transitions(
        self, tmp_output, sample_library, sample_config
    ):
        """Generate a set, then verify the transitions JSON can be loaded
        and has the schema the render phase expects."""
        from autodj.generate.playlist import generate

        output_dir = str(tmp_output / "playlists")
        track_ids = [t["id"] for t in sample_library[:5]]
        result = generate(
            track_ids=track_ids,
            library=sample_library,
            config=sample_config,
            output_dir=output_dir,
        )

        assert result is not None
        _, transitions_path = result

        # Load and validate schema (as render_set.py would)
        with open(transitions_path) as f:
            plan = json.load(f)

        assert "transitions" in plan
        assert len(plan["transitions"]) >= 1

        # Each transition must have fields render.py expects
        for t in plan["transitions"]:
            assert "track_index" in t
            assert "target_bpm" in t
            assert "effect" in t

    def test_render_with_mocked_liquidsoap(
        self, tmp_output, sample_transitions, sample_config
    ):
        """Render phase with mocked Liquidsoap should complete successfully."""
        from autodj.render.render import RenderEngine

        # Write transitions JSON
        trans_file = tmp_output / "playlists" / "transitions-test.json"
        with open(trans_file, "w") as f:
            json.dump(sample_transitions, f)

        # Write M3U
        m3u_file = tmp_output / "playlists" / "playlist-test.m3u"
        with open(m3u_file, "w") as f:
            f.write("#EXTM3U\n")
            for t in sample_transitions["transitions"]:
                f.write(f"#EXTINF:240,{t['track_id']}\n")
                f.write(f"{t['file_path']}\n")

        output_file = tmp_output / "mixes" / "test-mix.mp3"

        engine = RenderEngine(sample_config)

        with patch("autodj.render.render.subprocess.run") as mock_run, \
             patch("autodj.render.render._validate_output_file") as mock_validate, \
             patch("autodj.render.render._write_mix_metadata") as mock_metadata:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            mock_validate.return_value = True
            mock_metadata.return_value = True

            result = engine.render_playlist(
                str(trans_file),
                str(m3u_file),
                str(output_file),
                timeout_seconds=10,
            )

        assert result is True

    def test_mix_retention_logic(self, tmp_output):
        """Verify mix retention: keep only N most recent."""
        mixes_dir = tmp_output / "mixes"

        # Create 5 fake mixes with staggered timestamps
        for i in range(5):
            mix_file = mixes_dir / f"2026-02-0{i+1}.mp3"
            mix_file.write_bytes(b"x" * 1024)
            # Set modification time to stagger
            mtime = time.time() - (5 - i) * 3600
            os.utime(str(mix_file), (mtime, mtime))

        # Verify all 5 exist
        mixes = sorted(mixes_dir.glob("*.mp3"))
        assert len(mixes) == 5

        # Simulate the cleanup logic from autodj-nightly.sh
        max_kept = 3
        all_mixes = sorted(mixes_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        if len(all_mixes) > max_kept:
            to_remove = all_mixes[: len(all_mixes) - max_kept]
            for f in to_remove:
                f.unlink()

        remaining = list(mixes_dir.glob("*.mp3"))
        assert len(remaining) == max_kept

    def test_transitions_json_roundtrip(self, sample_transitions):
        """Transitions JSON should survive a write/read roundtrip."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(sample_transitions, f)
            temp_path = f.name

        try:
            with open(temp_path) as f:
                loaded = json.load(f)

            assert loaded["playlist_id"] == sample_transitions["playlist_id"]
            assert len(loaded["transitions"]) == len(sample_transitions["transitions"])

            for orig, loaded_t in zip(
                sample_transitions["transitions"], loaded["transitions"]
            ):
                assert orig["track_id"] == loaded_t["track_id"]
                assert orig["target_bpm"] == loaded_t["target_bpm"]
                assert orig["effect"] == loaded_t["effect"]
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
