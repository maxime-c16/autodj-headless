"""
Unit tests for Liquidsoap render pipeline.

Tests script generation, rendering, and file handling.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from autodj.render.render import (
    _generate_liquidsoap_script,
    _validate_output_file,
    _write_mix_metadata,
    _cleanup_partial_output,
    RenderEngine,
)


@pytest.fixture
def config():
    """Test configuration."""
    return {
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 192,
            "crossfade_duration_seconds": 4.0,
            "time_stretch_quality": "high",
        }
    }


@pytest.fixture
def sample_plan():
    """Sample transitions plan."""
    return {
        "playlist_id": "test-playlist-1",
        "mix_duration_seconds": 600,
        "generated_at": "2026-01-06T14:00:00",
        "transitions": [
            {
                "track_index": 0,
                "track_id": "track-1",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 126.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 4.0,
                "effect": "smart_crossfade",
                "next_track_id": "track-2",
            },
            {
                "track_index": 1,
                "track_id": "track-2",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 128.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 4.0,
                "effect": "smart_crossfade",
                "next_track_id": None,
            },
        ],
    }


class TestLiquidsoapScriptGeneration:
    """Test Liquidsoap script generation."""

    def test_generate_script_basic(self, sample_plan, config):
        """Generate basic Liquidsoap script."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert script
        assert "set(\"clock.sync\", false)" in script
        assert "smart_crossfade" in script
        assert "load_track" in script

    def test_script_includes_offline_clock(self, sample_plan, config):
        """Script includes offline clock setting."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "set(\"clock.sync\", false)" in script

    def test_script_includes_tracks(self, sample_plan, config):
        """Script loads all transitions."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # Should mention both tracks
        assert "Track 1" in script
        assert "Track 2" in script

    def test_script_includes_crossfade(self, sample_plan, config):
        """Script includes crossfade configuration."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "smart_crossfade" in script
        assert "4.0" in script  # crossfade duration

    def test_script_mp3_output(self, sample_plan, config):
        """Script generates MP3 output."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "%%mp3" in script
        assert "192" in script  # bitrate

    def test_script_flac_output(self, sample_plan, config):
        """Script can generate FLAC output."""
        config["render"]["output_format"] = "flac"
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.flac", config)

        assert "%%flac" in script

    def test_script_empty_transitions(self, config):
        """Script generation handles empty transitions."""
        plan = {
            "playlist_id": "empty",
            "transitions": [],
        }

        script = _generate_liquidsoap_script(plan, "/tmp/mix.mp3", config)

        # Should return empty or error
        assert not script or "error" in script.lower()

    def test_script_with_custom_crossfade(self, sample_plan, config):
        """Script respects custom crossfade duration."""
        config["render"]["crossfade_duration_seconds"] = 6.0
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "6.0" in script


class TestRenderEngine:
    """Test RenderEngine orchestration."""

    def test_engine_initialization(self, config):
        """RenderEngine initializes with config."""
        engine = RenderEngine(config)

        assert engine.config == config

    def test_render_playlist_success(self, config, sample_plan):
        """Successful playlist rendering."""
        engine = RenderEngine(config)

        # Create temporary files
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create transitions JSON
            trans_file = tmpdir_path / "transitions.json"
            with open(trans_file, "w") as f:
                json.dump(sample_plan, f)

            # Create playlist M3U
            m3u_file = tmpdir_path / "playlist.m3u"
            with open(m3u_file, "w") as f:
                f.write("#EXTM3U\n")
                f.write("#EXT-INF:180,track1\n")
                f.write("/music/track1.mp3\n")
                f.write("#EXT-INF:180,track2\n")
                f.write("/music/track2.mp3\n")

            output_file = tmpdir_path / "mix.mp3"

            # Mock subprocess to avoid actual Liquidsoap execution
            with patch("autodj.render.render.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

                result = engine.render_playlist(
                    str(trans_file),
                    str(m3u_file),
                    str(output_file),
                    timeout_seconds=10,
                )

            assert result is True
            mock_run.assert_called_once()

    def test_render_playlist_missing_transitions(self, config):
        """Handle missing transitions file."""
        engine = RenderEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            m3u_file = tmpdir_path / "playlist.m3u"
            m3u_file.write_text("#EXTM3U\n")

            output_file = tmpdir_path / "mix.mp3"

            result = engine.render_playlist(
                str(tmpdir_path / "nonexistent.json"),
                str(m3u_file),
                str(output_file),
            )

            assert result is False

    def test_render_playlist_missing_m3u(self, config, sample_plan):
        """Handle missing M3U file."""
        engine = RenderEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create transitions JSON
            trans_file = tmpdir_path / "transitions.json"
            with open(trans_file, "w") as f:
                json.dump(sample_plan, f)

            output_file = tmpdir_path / "mix.mp3"

            result = engine.render_playlist(
                str(trans_file),
                str(tmpdir_path / "nonexistent.m3u"),
                str(output_file),
            )

            assert result is False

    def test_render_playlist_liquidsoap_failure(self, config, sample_plan):
        """Handle Liquidsoap execution failure."""
        engine = RenderEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            trans_file = tmpdir_path / "transitions.json"
            with open(trans_file, "w") as f:
                json.dump(sample_plan, f)

            m3u_file = tmpdir_path / "playlist.m3u"
            m3u_file.write_text("#EXTM3U\n#EXT-INF:180,track1\n/music/track1.mp3\n")

            output_file = tmpdir_path / "mix.mp3"

            with patch("autodj.render.render.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stderr="Liquidsoap error", stdout=""
                )

                result = engine.render_playlist(
                    str(trans_file),
                    str(m3u_file),
                    str(output_file),
                    timeout_seconds=10,
                )

            assert result is False

    def test_render_playlist_timeout(self, config, sample_plan):
        """Handle rendering timeout."""
        engine = RenderEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            trans_file = tmpdir_path / "transitions.json"
            with open(trans_file, "w") as f:
                json.dump(sample_plan, f)

            m3u_file = tmpdir_path / "playlist.m3u"
            m3u_file.write_text("#EXTM3U\n#EXT-INF:180,track1\n/music/track1.mp3\n")

            output_file = tmpdir_path / "mix.mp3"

            with patch("autodj.render.render.subprocess.run") as mock_run:
                import subprocess

                mock_run.side_effect = subprocess.TimeoutExpired("liquidsoap", 10)

                result = engine.render_playlist(
                    str(trans_file),
                    str(m3u_file),
                    str(output_file),
                    timeout_seconds=10,
                )

            assert result is False

    def test_render_playlist_maps_file_paths(self, config, sample_plan):
        """File paths from M3U are mapped to transitions."""
        engine = RenderEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            trans_file = tmpdir_path / "transitions.json"
            with open(trans_file, "w") as f:
                json.dump(sample_plan, f)

            m3u_file = tmpdir_path / "playlist.m3u"
            with open(m3u_file, "w") as f:
                f.write("#EXTM3U\n")
                f.write("#EXT-INF:180,track1\n")
                f.write("/music/track1.mp3\n")
                f.write("#EXT-INF:180,track2\n")
                f.write("/music/track2.mp3\n")

            output_file = tmpdir_path / "mix.mp3"

            with patch("autodj.render.render.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

                engine.render_playlist(
                    str(trans_file),
                    str(m3u_file),
                    str(output_file),
                )

                # Check that subprocess was called with generated script
                assert mock_run.called


class TestRenderIntegration:
    """Integration tests for rendering."""

    def test_end_to_end_script_generation(self, sample_plan, config):
        """Generate and validate complete Liquidsoap script."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # Script should be valid Liquidsoap syntax (basic checks)
        assert "def " in script
        assert "sequence" in script
        assert "output.file" in script

        # Should have proper structure
        lines = script.split("\n")
        assert len(lines) > 10

    def test_render_respects_config(self, sample_plan, config):
        """Rendering respects configuration parameters."""
        config["render"]["mp3_bitrate"] = 320
        config["render"]["crossfade_duration_seconds"] = 8.0

        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "320" in script
        assert "8.0" in script


class TestOutputValidation:
    """Test output file validation."""

    def test_validate_nonexistent_file(self):
        """Validation fails for nonexistent files."""
        result = _validate_output_file("/nonexistent/path/file.mp3")
        assert result is False

    def test_validate_file_too_small(self):
        """Validation fails for files smaller than 1 MiB."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
            f.write(b"small")

        try:
            result = _validate_output_file(temp_path)
            assert result is False
        finally:
            Path(temp_path).unlink()

    def test_validate_large_file(self):
        """Validation passes for large files."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
            # Write 2 MiB of data
            f.write(b"x" * (2 * 1024 * 1024))

        try:
            result = _validate_output_file(temp_path)
            assert result is True
        finally:
            Path(temp_path).unlink()


class TestMetadataWriting:
    """Test ID3 metadata writing."""

    def test_write_metadata_nonexistent_file(self):
        """Metadata writing fails for nonexistent files."""
        result = _write_mix_metadata("/nonexistent/file.mp3", "test-id", "2026-01-06T10:00:00")
        assert result is False

    @patch("autodj.render.render.EasyID3")
    def test_write_metadata_mp3(self, mock_easyid3):
        """Metadata writing works for MP3 files."""
        mock_instance = MagicMock()
        mock_easyid3.return_value = mock_instance

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
            f.write(b"x" * (2 * 1024 * 1024))

        try:
            result = _write_mix_metadata(temp_path, "test-id", "2026-01-06T10:00:00")
            assert result is True
            # Verify metadata was set
            mock_instance.__setitem__.assert_any_call("album", "AutoDJ Mix 2026-01-06")
            mock_instance.__setitem__.assert_any_call("genre", "DJ Mix")
            mock_instance.__setitem__.assert_any_call("date", "2026")
            mock_instance.save.assert_called_once()
        finally:
            Path(temp_path).unlink()

    @patch("autodj.render.render.FLAC")
    def test_write_metadata_flac(self, mock_flac):
        """Metadata writing works for FLAC files."""
        mock_instance = MagicMock()
        mock_flac.return_value = mock_instance

        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
            temp_path = f.name
            f.write(b"x" * (2 * 1024 * 1024))

        try:
            result = _write_mix_metadata(temp_path, "test-id", "2026-01-06T10:00:00")
            assert result is True
            # Verify metadata was set
            mock_instance.__setitem__.assert_any_call("album", "AutoDJ Mix 2026-01-06")
            mock_instance.__setitem__.assert_any_call("genre", "DJ Mix")
            mock_instance.__setitem__.assert_any_call("date", "2026")
            mock_instance.save.assert_called_once()
        finally:
            Path(temp_path).unlink()

    def test_write_metadata_unsupported_format(self):
        """Metadata writing returns False for unsupported formats."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            f.write(b"x" * (2 * 1024 * 1024))

        try:
            result = _write_mix_metadata(temp_path, "test-id", "2026-01-06T10:00:00")
            assert result is False
        finally:
            Path(temp_path).unlink()


class TestPartialCleanup:
    """Test cleanup of partial output files."""

    def test_cleanup_existing_file(self):
        """Cleanup removes existing files."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
            f.write(b"partial")

        assert Path(temp_path).exists()
        _cleanup_partial_output(temp_path)
        assert not Path(temp_path).exists()

    def test_cleanup_nonexistent_file(self):
        """Cleanup handles nonexistent files gracefully."""
        # Should not raise an exception
        _cleanup_partial_output("/nonexistent/file.mp3")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
