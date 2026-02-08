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
    _generate_liquidsoap_script_legacy,
    _generate_liquidsoap_script_v2,
    _preprocess_loops,
    _validate_output_file,
    _write_mix_metadata,
    _cleanup_partial_output,
    _frames_to_seconds,
    _calculate_stretch_ratio,
    RenderEngine,
)
from autodj.render.loop_extract import (
    extract_segment,
    create_loop_hold,
    create_loop_roll,
    create_temp_loop_dir,
    cleanup_temp_loops,
)
from autodj.generate.playlist import (
    TransitionType,
    TransitionSpec,
    TransitionPlan,
    ArchwizardPhonemius,
    _are_keys_compatible,
)


@pytest.fixture
def config():
    """Test configuration."""
    return {
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 320,
            "crossfade_duration_seconds": 4.0,
            "time_stretch_quality": "high",
        }
    }


@pytest.fixture
def sample_plan():
    """Sample transitions plan with full metadata."""
    return {
        "playlist_id": "test-playlist-1",
        "mix_duration_seconds": 600,
        "generated_at": "2026-01-06T14:00:00",
        "transitions": [
            {
                "track_index": 0,
                "track_id": "track-1",
                "file_path": "/music/track1.mp3",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 127.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 15.1,
                "effect": "smart_crossfade",
                "next_track_id": "track-2",
                "bpm": 126.0,
                "cue_in_frames": 44100,
                "cue_out_frames": 11025000,
                "title": "Test Track 1",
                "artist": "Artist A",
                "outro_start_seconds": 230.0,
                "drop_position_seconds": None,
            },
            {
                "track_index": 1,
                "track_id": "track-2",
                "file_path": "/music/track2.mp3",
                "entry_cue": "cue_in",
                "hold_duration_bars": 16,
                "target_bpm": 128.0,
                "exit_cue": "cue_out",
                "mix_out_seconds": 15.0,
                "effect": "smart_crossfade",
                "next_track_id": None,
                "bpm": 128.0,
                "cue_in_frames": 0,
                "cue_out_frames": 10584000,
                "title": "Test Track 2",
                "artist": "Artist B",
                "outro_start_seconds": 220.0,
                "drop_position_seconds": 30.0,
            },
        ],
    }


class TestLiquidsoapScriptGeneration:
    """Test Liquidsoap script generation."""

    def test_generate_script_basic(self, sample_plan, config):
        """Generate basic Liquidsoap script."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert script
        assert "single(" in script

    def test_script_includes_offline_clock(self, sample_plan, config):
        """Script includes offline clock setting (sync=none for no real-time wait)."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert 'clock(sync="none"' in script

    def test_script_includes_tracks(self, sample_plan, config):
        """Script loads all transitions."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # Should mention both tracks
        assert "Track 1" in script
        assert "Track 2" in script

    def test_script_includes_crossfade(self, sample_plan, config):
        """Script includes crossfade via cross() function."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "cross(" in script
        assert "dj_transition" in script

    def test_script_mp3_output(self, sample_plan, config):
        """Script generates MP3 output."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "%mp3" in script
        assert "320" in script  # bitrate

    def test_script_flac_output(self, sample_plan, config):
        """Script can generate FLAC output."""
        config["render"]["output_format"] = "flac"
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.flac", config)

        assert "%flac" in script

    def test_script_empty_transitions(self, config):
        """Script generation handles empty transitions."""
        plan = {
            "playlist_id": "empty",
            "transitions": [],
        }

        script = _generate_liquidsoap_script(plan, "/tmp/mix.mp3", config)

        # Should return empty or error
        assert not script or "error" in script.lower()

    def test_script_with_custom_crossfade_fallback(self, config):
        """Script uses config crossfade as fallback when no BPM data."""
        config["render"]["crossfade_duration_seconds"] = 6.0
        plan = {
            "playlist_id": "no-bpm",
            "transitions": [
                {"track_index": 0, "track_id": "t1", "file_path": "/music/t1.mp3"},
                {"track_index": 1, "track_id": "t2", "file_path": "/music/t2.mp3"},
            ],
        }
        script = _generate_liquidsoap_script(plan, "/tmp/mix.mp3", config)

        assert "6.0" in script


class TestCrossfadeArchitecture:
    """Regression tests to prevent re-introducing the overlay bug."""

    def test_script_uses_sequence_not_overlay(self, sample_plan, config):
        """Script must use sequence([...]) + cross() for sequential playback."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "sequence([" in script
        assert "cross(" in script

    def test_bpm_data_flows_to_script(self, sample_plan, config):
        """When bpm != target_bpm, stretch(ratio=...) must appear."""
        # Track 1 has bpm=126, target_bpm=127 → stretch ratio ≈ 1.008
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "stretch(ratio=" in script

    def test_single_track_no_cross(self, config):
        """Single track should not use sequence/cross in code (comments OK)."""
        plan = {
            "playlist_id": "single",
            "transitions": [
                {
                    "track_index": 0,
                    "track_id": "only",
                    "file_path": "/music/only.mp3",
                    "bpm": 128.0,
                    "target_bpm": 128.0,
                },
            ],
        }
        script = _generate_liquidsoap_script(plan, "/tmp/mix.mp3", config)

        # Filter out comments to check actual code
        code_lines = [l for l in script.split("\n") if not l.strip().startswith("#")]
        code_only = "\n".join(code_lines)

        assert "sequence([" not in code_only
        assert "cross(" not in code_only

    def test_script_has_bass_swap(self, sample_plan, config):
        """Script must use high-pass filter on outgoing track for bass swap."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "butterworth.high(frequency=200.0" in script

    def test_script_has_limiter(self, sample_plan, config):
        """Script must have a compressor/limiter on master output."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "compress(" in script

    def test_script_has_sub_bass_filter(self, sample_plan, config):
        """Script must have butterworth high-pass at 30Hz for sub-bass removal."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "butterworth.high(frequency=30.0" in script

    def test_cue_points_applied(self, sample_plan, config):
        """Cue point frames should be converted to seconds and used via annotate + cue_cut."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # Track 1 has cue_in_frames=44100 → 1.000s, cue_out_frames=11025000 → 250.000s
        assert "cue_cut(" in script
        assert "liq_cue_in=1.000" in script  # cue_in_sec for track 1

    def test_bar_aligned_crossfade_duration(self, sample_plan, config):
        """Crossfade should be ~15s (8 bars at ~127 BPM), not fixed 4.0s."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # avg BPM = (126 + 128) / 2 = 127, 8 bars = 8*4*60/127 ≈ 15.1s
        # The script should NOT use the 4.0s fallback
        assert "duration=4.0" not in script

    def test_outro_start_overrides_cue_out(self, sample_plan, config):
        """When outro_start_seconds is set, cue_out should use it."""
        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        # Track 1 has outro_start_seconds=230.0 → should appear as liq_cue_out
        assert "liq_cue_out=230.000" in script


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

            # Mock subprocess and validation
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
            mock_run.assert_called_once()
            mock_validate.assert_called_once_with(str(output_file))
            mock_metadata.assert_called_once()

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

        # Script should use sequence + cross architecture
        assert "sequence(" in script
        assert "cross(" in script
        assert "output.file" in script

        # Should have proper structure
        lines = script.split("\n")
        assert len(lines) > 10

    def test_render_respects_config(self, sample_plan, config):
        """Rendering respects configuration parameters."""
        config["render"]["mp3_bitrate"] = 256

        script = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)

        assert "256" in script


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

    @patch("autodj.render.render.EasyID3")
    def test_write_metadata_with_transitions(self, mock_easyid3):
        """Metadata writing includes artist from transitions."""
        mock_instance = MagicMock()
        mock_easyid3.return_value = mock_instance

        transitions = [
            {"artist": "Klangkuenstler", "title": "Deine Angst"},
            {"artist": "FJAAK", "title": "Drift"},
        ]

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
            f.write(b"x" * (2 * 1024 * 1024))

        try:
            result = _write_mix_metadata(temp_path, "test-id", "2026-01-06T10:00:00", transitions=transitions)
            assert result is True
            mock_instance.__setitem__.assert_any_call("title", "AutoDJ Mix - Klangkuenstler et al.")
            mock_instance.__setitem__.assert_any_call("artist", "AutoDJ")
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


class TestExcludeDirs:
    """Test EXCLUDE_DIRS filtering in analyze_library."""

    def test_exclude_automix_directory(self, tmp_path):
        """Tracks in automix/ should be excluded from analysis."""
        # Read the source file to verify EXCLUDE_DIRS without importing
        # (avoids toml dependency which may not be installed system-wide)
        source = Path("/home/mcauchy/autodj-headless/src/scripts/analyze_library.py").read_text()
        assert "automix" in source
        assert "EXCLUDE_DIRS" in source

        # Verify the filtering logic inline (simulate discover_audio_files)
        exclude_dirs = {"automix", "autodj-output", "mixes"}

        music_dir = tmp_path / "music"
        music_dir.mkdir()
        (music_dir / "good_track.mp3").write_bytes(b"audio")
        automix_dir = music_dir / "automix"
        automix_dir.mkdir()
        (automix_dir / "generated_mix.mp3").write_bytes(b"audio")

        # Simulate the filtering logic from analyze_library.py
        all_files = list(music_dir.rglob("*.mp3"))
        assert len(all_files) == 2  # both files discovered

        filtered = [f for f in all_files if not any(part in exclude_dirs for part in f.parts)]
        assert len(filtered) == 1  # automix file excluded
        assert filtered[0].name == "good_track.mp3"


class TestAubioVersionAttribute:
    """Test aubio version attribute handling in cues.py."""

    def test_aubio_version_uses_getattr(self):
        """Cues module should use getattr(aubio, 'version') not aubio.__version__."""
        cues_source = Path("/home/mcauchy/autodj-headless/src/autodj/analyze/cues.py").read_text()

        # Should NOT use __version__
        assert "__version__" not in cues_source
        # Should use getattr or .version
        assert "aubio.version" in cues_source or "getattr(aubio" in cues_source


# ==============================================================================
# PRO DJ v2 TESTS
# ==============================================================================


@pytest.fixture
def v2_plan_bass_swap():
    """Plan with all bass_swap transitions (default)."""
    return {
        "playlist_id": "v2-test",
        "mix_duration_seconds": 600,
        "transitions": [
            {
                "track_index": 0, "track_id": "t1",
                "file_path": "/music/track1.mp3",
                "bpm": 128.0, "target_bpm": 128.0,
                "cue_in_frames": 0, "cue_out_frames": 11289600,  # 256s
                "title": "Track A", "artist": "DJ A",
                "next_track_id": "t2",
                "transition_type": "bass_swap",
                "overlap_bars": 8,
                "hpf_frequency": 200.0,
                "lpf_frequency": 2500.0,
            },
            {
                "track_index": 1, "track_id": "t2",
                "file_path": "/music/track2.mp3",
                "bpm": 130.0, "target_bpm": 129.0,
                "cue_in_frames": 0, "cue_out_frames": 10584000,  # 240s
                "title": "Track B", "artist": "DJ B",
                "next_track_id": None,
                "transition_type": "bass_swap",
                "overlap_bars": 8,
                "hpf_frequency": 200.0,
                "lpf_frequency": 2500.0,
            },
        ],
    }


@pytest.fixture
def v2_plan_mixed_transitions():
    """Plan with multiple transition types."""
    return {
        "playlist_id": "v2-mixed-test",
        "mix_duration_seconds": 900,
        "transitions": [
            {
                "track_index": 0, "track_id": "t1",
                "file_path": "/music/track1.mp3",
                "bpm": 128.0, "target_bpm": 128.0,
                "cue_in_frames": 0, "cue_out_frames": 11289600,
                "title": "Track A", "artist": "DJ A",
                "next_track_id": "t2",
                "transition_type": "loop_hold",
                "overlap_bars": 16,
                "loop_start_seconds": 200.0,
                "loop_end_seconds": 215.0,
                "loop_bars": 8,
                "loop_repeats": 2,
                "_loop_wav_path": "/tmp/autodj_loops/t0_loop.wav",
                "hpf_frequency": 200.0,
                "lpf_frequency": 2500.0,
            },
            {
                "track_index": 1, "track_id": "t2",
                "file_path": "/music/track2.mp3",
                "bpm": 130.0, "target_bpm": 129.0,
                "cue_in_frames": 0, "cue_out_frames": 10584000,
                "title": "Track B", "artist": "DJ B",
                "next_track_id": "t3",
                "transition_type": "drop_swap",
                "overlap_bars": 4,
                "drop_position_seconds": 45.0,
                "hpf_frequency": 200.0,
                "lpf_frequency": 20000.0,
            },
            {
                "track_index": 2, "track_id": "t3",
                "file_path": "/music/track3.mp3",
                "bpm": 126.0, "target_bpm": 126.0,
                "cue_in_frames": 0, "cue_out_frames": 12348000,
                "title": "Track C", "artist": "DJ C",
                "next_track_id": None,
                "transition_type": "bass_swap",
                "overlap_bars": 8,
                "hpf_frequency": 200.0,
                "lpf_frequency": 2500.0,
            },
        ],
    }


class TestTransitionDecisionEngine:
    """Test ArchwizardPhonemius._choose_transition() logic."""

    def _make_phonemius(self):
        """Create a Phonemius instance with mock db."""
        mock_db = Mock()
        mock_db.get_track_analysis = Mock(return_value=None)
        config = {"constraints": {}, "render": {"crossfade_duration_seconds": 4.0}}
        return ArchwizardPhonemius(mock_db, config)

    def test_bass_swap_as_default(self):
        """With no analysis data, bass_swap is chosen."""
        p = self._make_phonemius()
        spec = p._choose_transition(
            outgoing_analysis=None,
            incoming_analysis=None,
            outgoing_track={"bpm": 128.0, "key": "8A"},
            incoming_track={"bpm": 128.0, "key": "8A"},
            prev_type=None,
        )
        assert spec.type == TransitionType.BASS_SWAP
        assert spec.overlap_bars == 8

    def test_loop_hold_chosen_when_stable_loop_exists(self):
        """loop_hold chosen when outgoing has stable loop + incoming has intro."""
        p = self._make_phonemius()
        out_analysis = {
            "loop_regions": [
                {"label": "outro_loop", "stability": 0.8,
                 "start_seconds": 200.0, "end_seconds": 215.0, "length_bars": 8},
            ],
            "sections": [{"label": "outro"}],
        }
        in_analysis = {
            "sections": [{"label": "intro"}],
            "cue_points": [],
        }
        spec = p._choose_transition(
            outgoing_analysis=out_analysis,
            incoming_analysis=in_analysis,
            outgoing_track={"bpm": 128.0, "key": "8A"},
            incoming_track={"bpm": 128.0, "key": "8A"},
            prev_type=None,
        )
        assert spec.type == TransitionType.LOOP_HOLD
        assert spec.loop_start_seconds == 200.0
        assert spec.loop_end_seconds == 215.0
        assert spec.loop_repeats == 2

    def test_drop_swap_chosen_when_incoming_has_drop(self):
        """drop_swap chosen when incoming has drop_1 + outgoing has breakdown."""
        p = self._make_phonemius()
        out_analysis = {
            "loop_regions": [],
            "sections": [{"label": "breakdown"}],
        }
        in_analysis = {
            "sections": [],
            "cue_points": [{"label": "drop_1", "position_seconds": 45.0}],
        }
        spec = p._choose_transition(
            outgoing_analysis=out_analysis,
            incoming_analysis=in_analysis,
            outgoing_track={"bpm": 128.0, "key": "8A"},
            incoming_track={"bpm": 130.0, "key": "9A"},
            prev_type=None,
        )
        assert spec.type == TransitionType.DROP_SWAP
        assert spec.overlap_bars == 4

    def test_no_consecutive_same_type(self):
        """Same transition type should not repeat consecutively."""
        p = self._make_phonemius()
        # First call: bass_swap (default)
        spec1 = p._choose_transition(
            outgoing_analysis=None,
            incoming_analysis=None,
            outgoing_track={"bpm": 128.0, "key": "8A"},
            incoming_track={"bpm": 128.0, "key": "8A"},
            prev_type=None,
        )
        assert spec1.type == TransitionType.BASS_SWAP

        # Second call with prev_type=BASS_SWAP: should pick something different
        # if there's ANY viable alternative. With eq_blend eligible (same key, same energy):
        spec2 = p._choose_transition(
            outgoing_analysis=None,
            incoming_analysis=None,
            outgoing_track={"bpm": 128.0, "key": "8A", "energy": 0.5},
            incoming_track={"bpm": 128.0, "key": "8A", "energy": 0.5},
            prev_type=TransitionType.BASS_SWAP,
        )
        # eq_blend scores 2.0 vs bass_swap 1.0 * 0.1 = 0.1
        assert spec2.type == TransitionType.EQ_BLEND

    def test_fallback_when_no_analysis(self):
        """No analysis data => always bass_swap (score 1.0)."""
        p = self._make_phonemius()
        spec = p._choose_transition(
            outgoing_analysis=None,
            incoming_analysis=None,
            outgoing_track={"bpm": 128.0},
            incoming_track={"bpm": 128.0},
            prev_type=None,
        )
        assert spec.type == TransitionType.BASS_SWAP

    def test_final_track_always_bass_swap(self):
        """Last track (no incoming) always gets bass_swap."""
        p = self._make_phonemius()
        spec = p._choose_transition(
            outgoing_analysis={"loop_regions": [{"label": "outro_loop", "stability": 0.9,
                                                  "start_seconds": 200.0, "end_seconds": 215.0, "length_bars": 8}]},
            incoming_analysis=None,
            outgoing_track={"bpm": 128.0},
            incoming_track=None,
            prev_type=None,
        )
        assert spec.type == TransitionType.BASS_SWAP

    def test_loop_roll_chosen_with_drop_loop(self):
        """loop_roll chosen when outgoing has drop_loop + high energy."""
        p = self._make_phonemius()
        out_analysis = {
            "loop_regions": [
                {"label": "drop_loop", "stability": 0.7,
                 "start_seconds": 100.0, "end_seconds": 115.0, "length_bars": 8},
            ],
            "sections": [],
        }
        spec = p._choose_transition(
            outgoing_analysis=out_analysis,
            incoming_analysis={"sections": [], "cue_points": []},
            outgoing_track={"bpm": 128.0, "key": "8A", "energy": 0.8},
            incoming_track={"bpm": 128.0, "key": "3B"},
            prev_type=None,
        )
        assert spec.type == TransitionType.LOOP_ROLL
        assert spec.roll_stages == [(8, 1), (4, 1), (2, 1), (1, 2)]

    def test_eq_blend_chosen_with_similar_energy_and_keys(self):
        """eq_blend chosen when energy similar + keys compatible."""
        p = self._make_phonemius()
        spec = p._choose_transition(
            outgoing_analysis={"loop_regions": [], "sections": []},
            incoming_analysis={"sections": [], "cue_points": []},
            outgoing_track={"bpm": 128.0, "key": "8A", "energy": 0.5},
            incoming_track={"bpm": 128.0, "key": "8B", "energy": 0.5},
            prev_type=None,
        )
        assert spec.type == TransitionType.EQ_BLEND
        assert spec.overlap_bars == 32


class TestKeyCompatibility:
    """Test Camelot key compatibility helper."""

    def test_same_key(self):
        assert _are_keys_compatible("8A", "8A") is True

    def test_parallel_mode(self):
        assert _are_keys_compatible("8A", "8B") is True

    def test_adjacent_up(self):
        assert _are_keys_compatible("8A", "9A") is True

    def test_adjacent_down(self):
        assert _are_keys_compatible("8B", "7B") is True

    def test_wrap_around(self):
        assert _are_keys_compatible("12A", "1A") is True

    def test_incompatible(self):
        assert _are_keys_compatible("8A", "3A") is False

    def test_unknown_wildcard(self):
        assert _are_keys_compatible("", "8A") is True
        assert _are_keys_compatible("8A", "") is True


class TestLoopExtraction:
    """Test ffmpeg loop pre-processing (mocked subprocess)."""

    @patch("autodj.render.loop_extract.subprocess.run")
    def test_extract_segment(self, mock_run):
        """extract_segment calls ffmpeg with correct args."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # Create a non-empty file to pass the size check
            f.write(b"x" * 1000)
            out_path = f.name

        try:
            result = extract_segment("/music/track.mp3", 10.0, 5.0, out_path)
            assert result is True
            # Check ffmpeg was called with -ss and -t
            args = mock_run.call_args[0][0]
            assert "ffmpeg" in args[0]
            assert "-ss" in args
            assert "10.000" in args
            assert "-t" in args
            assert "5.000" in args
        finally:
            Path(out_path).unlink(missing_ok=True)

    @patch("autodj.render.loop_extract.extract_segment")
    @patch("autodj.render.loop_extract.subprocess.run")
    def test_create_loop_hold(self, mock_run, mock_extract):
        """create_loop_hold extracts and repeats loop."""
        mock_extract.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "loop.wav")
            result = create_loop_hold("/music/track.mp3", 100.0, 115.0, 2, out_path)
            assert result is True
            # extract_segment called for single loop period
            mock_extract.assert_called_once()
            # ffmpeg called for -stream_loop repeat
            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert "-stream_loop" in args
            assert "1" in args  # repeats-1 = 1 for 2x total

    @patch("autodj.render.loop_extract.extract_segment")
    @patch("autodj.render.loop_extract.create_loop_hold")
    @patch("autodj.render.loop_extract.subprocess.run")
    def test_create_loop_roll_stages(self, mock_run, mock_hold, mock_extract):
        """create_loop_roll generates progressive stages."""
        mock_extract.return_value = True
        mock_hold.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        stages = [(8, 1), (4, 1), (2, 1), (1, 2)]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "roll.wav")
            result = create_loop_roll("/music/track.mp3", 100.0, 128.0, stages, out_path)
            assert result is True
            # Should have called extract for stages with reps=1
            # and create_loop_hold for stages with reps>1

    def test_cleanup_temp_files(self):
        """cleanup_temp_loops removes temp directory."""
        temp_dir = create_temp_loop_dir()
        assert Path(temp_dir).exists()
        # Create a file in it
        test_file = Path(temp_dir) / "test.wav"
        test_file.write_bytes(b"test")
        cleanup_temp_loops(temp_dir)
        assert not Path(temp_dir).exists()

    def test_cleanup_nonexistent_dir(self):
        """cleanup handles nonexistent dir gracefully."""
        cleanup_temp_loops("/nonexistent/path/1234")


class TestManualAssemblyScript:
    """Test new v2 script generator."""

    def test_bass_swap_script(self, v2_plan_bass_swap, config):
        """v2 bass_swap generates correct Liquidsoap."""
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.mp3", config)
        assert script
        assert "Pro DJ Mix v2" in script
        assert "body_0" in script
        assert "body_1" in script
        assert "transition_0_1" in script
        assert "butterworth.high(frequency=200.0" in script
        assert "butterworth.low(frequency=2500.0" in script
        assert "add(normalize=false" in script
        assert "sequence([" in script

    def test_loop_hold_script_uses_wav(self, v2_plan_mixed_transitions, config):
        """loop_hold transition references pre-extracted WAV file."""
        script = _generate_liquidsoap_script_v2(v2_plan_mixed_transitions, "/tmp/mix.mp3", config)
        assert "/tmp/autodj_loops/t0_loop.wav" in script
        assert "LOOP_HOLD" in script

    def test_drop_swap_short_overlap(self, v2_plan_mixed_transitions, config):
        """drop_swap has short overlap and no LPF on incoming."""
        script = _generate_liquidsoap_script_v2(v2_plan_mixed_transitions, "/tmp/mix.mp3", config)
        assert "DROP_SWAP" in script
        # drop_swap: incoming at drop position with NO LPF
        # The outgoing has fade.out, incoming has fade.in but no butterworth.low on incoming
        lines = script.split("\n")
        # Find the DROP_SWAP section
        drop_section_start = None
        for i, line in enumerate(lines):
            if "DROP_SWAP" in line:
                drop_section_start = i
                break
        assert drop_section_start is not None
        # Check that drop_swap incoming doesn't have butterworth.low
        in_var_name = "t12_in"
        in_section_lines = [l for l in lines[drop_section_start:] if in_var_name in l]
        lpf_on_incoming = any("butterworth.low" in l for l in in_section_lines)
        assert not lpf_on_incoming, "drop_swap incoming should NOT have LPF"

    def test_eq_blend_long_overlap(self, config):
        """eq_blend generates 32-bar overlap."""
        plan = {
            "playlist_id": "eq-test",
            "transitions": [
                {
                    "track_index": 0, "track_id": "t1",
                    "file_path": "/music/t1.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 14112000,  # 320s
                    "title": "A", "artist": "A", "next_track_id": "t2",
                    "transition_type": "eq_blend",
                    "overlap_bars": 32,
                    "hpf_frequency": 800.0,
                    "lpf_frequency": 800.0,
                },
                {
                    "track_index": 1, "track_id": "t2",
                    "file_path": "/music/t2.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 13230000,
                    "title": "B", "artist": "B", "next_track_id": None,
                    "transition_type": "bass_swap",
                    "overlap_bars": 8,
                    "hpf_frequency": 200.0,
                    "lpf_frequency": 2500.0,
                },
            ],
        }
        script = _generate_liquidsoap_script_v2(plan, "/tmp/mix.mp3", config)
        assert "EQ_BLEND" in script
        assert "frequency=800.0" in script
        # 32 bars at 128 BPM = 32 * 4 * 60/128 = 60.0s
        assert "60.0" in script

    def test_loop_roll_script(self, config):
        """loop_roll references roll WAV file."""
        plan = {
            "playlist_id": "roll-test",
            "transitions": [
                {
                    "track_index": 0, "track_id": "t1",
                    "file_path": "/music/t1.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 11289600,
                    "title": "A", "artist": "A", "next_track_id": "t2",
                    "transition_type": "loop_roll",
                    "overlap_bars": 16,
                    "loop_start_seconds": 100.0,
                    "loop_end_seconds": 115.0,
                    "roll_stages": "[[8, 1], [4, 1], [2, 1], [1, 2]]",
                    "_loop_wav_path": "/tmp/autodj_loops/t0_roll.wav",
                    "hpf_frequency": 200.0,
                    "lpf_frequency": 2500.0,
                },
                {
                    "track_index": 1, "track_id": "t2",
                    "file_path": "/music/t2.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 10584000,
                    "title": "B", "artist": "B", "next_track_id": None,
                    "transition_type": "bass_swap",
                    "overlap_bars": 8,
                    "hpf_frequency": 200.0,
                    "lpf_frequency": 2500.0,
                },
            ],
        }
        script = _generate_liquidsoap_script_v2(plan, "/tmp/mix.mp3", config)
        assert "LOOP_ROLL" in script
        assert "/tmp/autodj_loops/t0_roll.wav" in script

    def test_sequence_no_cross(self, v2_plan_bass_swap, config):
        """v2 script uses sequence() but NEVER cross()."""
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.mp3", config)
        assert "sequence([" in script
        code_lines = [l for l in script.split("\n") if not l.strip().startswith("#")]
        code_only = "\n".join(code_lines)
        assert "cross(" not in code_only

    def test_single_track_no_transition(self, config):
        """Single track: body only, no transition zone."""
        plan = {
            "playlist_id": "single",
            "transitions": [{
                "track_index": 0, "track_id": "only",
                "file_path": "/music/only.mp3",
                "bpm": 128.0, "target_bpm": 128.0,
                "cue_in_frames": 0, "cue_out_frames": 10584000,
                "title": "Only", "artist": "Solo",
                "next_track_id": None,
                "transition_type": "bass_swap",
                "overlap_bars": 8,
                "hpf_frequency": 200.0,
                "lpf_frequency": 2500.0,
            }],
        }
        script = _generate_liquidsoap_script_v2(plan, "/tmp/mix.mp3", config)
        assert "body_0" in script
        assert "transition_" not in script
        # No sequence for single track
        code_lines = [l for l in script.split("\n") if not l.strip().startswith("#")]
        code_only = "\n".join(code_lines)
        assert "sequence([" not in code_only

    def test_backward_compat_no_transition_type(self, config):
        """Plans without transition_type field default to bass_swap behavior."""
        plan = {
            "playlist_id": "legacy",
            "transitions": [
                {
                    "track_index": 0, "track_id": "t1",
                    "file_path": "/music/t1.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 11289600,
                    "next_track_id": "t2",
                    # No transition_type, overlap_bars, hpf_frequency, etc.
                },
                {
                    "track_index": 1, "track_id": "t2",
                    "file_path": "/music/t2.mp3",
                    "bpm": 128.0, "target_bpm": 128.0,
                    "cue_in_frames": 0, "cue_out_frames": 10584000,
                    "next_track_id": None,
                },
            ],
        }
        script = _generate_liquidsoap_script_v2(plan, "/tmp/mix.mp3", config)
        assert script
        assert "butterworth.high(frequency=200.0" in script
        assert "butterworth.low(frequency=2500.0" in script

    def test_master_chain_unchanged(self, v2_plan_bass_swap, config):
        """v2 master chain has sub-bass filter + limiter (same as legacy)."""
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.mp3", config)
        assert "butterworth.high(frequency=30.0" in script
        assert "compress(threshold=-1.0" in script

    def test_track_splitting_cue_continuity(self, v2_plan_bass_swap, config):
        """Incoming body starts where transition head ended (cue continuity)."""
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.mp3", config)
        # Track 1 (idx=1) body should start after the 8-bar transition zone
        # At 128 BPM: 8 bars = 8*4*60/128 = 15.0s
        # So body_1 should have liq_cue_in=15.000
        assert "liq_cue_in=15.000" in script

    def test_v2_mp3_output(self, v2_plan_bass_swap, config):
        """v2 generates MP3 output with bitrate."""
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.mp3", config)
        assert "%mp3(bitrate=320)" in script
        assert 'clock(sync="none"' in script

    def test_v2_flac_output(self, v2_plan_bass_swap, config):
        """v2 generates FLAC output."""
        config["render"]["output_format"] = "flac"
        script = _generate_liquidsoap_script_v2(v2_plan_bass_swap, "/tmp/mix.flac", config)
        assert "%flac" in script

    def test_v2_empty_transitions(self, config):
        """v2 handles empty transitions."""
        plan = {"playlist_id": "empty", "transitions": []}
        script = _generate_liquidsoap_script_v2(plan, "/tmp/mix.mp3", config)
        assert not script


class TestTransitionPlanV2Fields:
    """Test new fields on TransitionPlan."""

    def test_default_values(self):
        """New fields have backward-compatible defaults."""
        plan = TransitionPlan(track_index=0, track_id="t1")
        assert plan.transition_type == "bass_swap"
        assert plan.overlap_bars == 8
        assert plan.hpf_frequency == 200.0
        assert plan.lpf_frequency == 2500.0
        assert plan.incoming_start_seconds is None
        assert plan.loop_start_seconds is None
        assert plan.roll_stages is None

    def test_to_dict_includes_v2_fields(self):
        """to_dict() includes new v2 fields."""
        plan = TransitionPlan(
            track_index=0, track_id="t1",
            transition_type="loop_hold",
            overlap_bars=16,
            loop_start_seconds=200.0,
            loop_end_seconds=215.0,
            loop_bars=8,
            loop_repeats=2,
        )
        d = plan.to_dict()
        assert d["transition_type"] == "loop_hold"
        assert d["overlap_bars"] == 16
        assert d["loop_start_seconds"] == 200.0
        assert d["loop_end_seconds"] == 215.0
        assert d["loop_bars"] == 8
        assert d["loop_repeats"] == 2

    def test_to_dict_omits_none_optional_fields(self):
        """to_dict() omits None optional fields."""
        plan = TransitionPlan(track_index=0, track_id="t1")
        d = plan.to_dict()
        assert "loop_start_seconds" not in d
        assert "roll_stages" not in d
        assert "incoming_start_seconds" not in d


class TestTransitionTypeEnum:
    """Test TransitionType enum."""

    def test_all_types(self):
        assert TransitionType.BASS_SWAP.value == "bass_swap"
        assert TransitionType.LOOP_HOLD.value == "loop_hold"
        assert TransitionType.DROP_SWAP.value == "drop_swap"
        assert TransitionType.LOOP_ROLL.value == "loop_roll"
        assert TransitionType.EQ_BLEND.value == "eq_blend"

    def test_from_string(self):
        assert TransitionType("bass_swap") == TransitionType.BASS_SWAP
        assert TransitionType("loop_hold") == TransitionType.LOOP_HOLD


class TestTransitionSpec:
    """Test TransitionSpec dataclass."""

    def test_bass_swap_defaults(self):
        spec = TransitionSpec(
            type=TransitionType.BASS_SWAP,
            overlap_bars=8,
            outgoing_end_seconds=0.0,
            incoming_start_seconds=15.0,
        )
        assert spec.hpf_frequency == 200.0
        assert spec.lpf_frequency == 2500.0
        assert spec.loop_start_seconds is None

    def test_loop_hold_with_loop_params(self):
        spec = TransitionSpec(
            type=TransitionType.LOOP_HOLD,
            overlap_bars=16,
            outgoing_end_seconds=200.0,
            incoming_start_seconds=30.0,
            loop_start_seconds=200.0,
            loop_end_seconds=215.0,
            loop_bars=8,
            loop_repeats=2,
        )
        assert spec.loop_bars == 8
        assert spec.loop_repeats == 2


class TestPreprocessLoops:
    """Test _preprocess_loops function."""

    def test_no_loops_returns_none(self, v2_plan_bass_swap, config):
        """Plan with only bass_swap transitions needs no loop preprocessing."""
        result = _preprocess_loops(v2_plan_bass_swap, config)
        assert result is None

    @patch("autodj.render.render.create_loop_hold")
    def test_loop_hold_preprocessing(self, mock_create, config):
        """loop_hold transition triggers loop extraction."""
        mock_create.return_value = True
        plan = {
            "transitions": [{
                "track_index": 0,
                "file_path": "/music/track.mp3",
                "bpm": 128.0,
                "transition_type": "loop_hold",
                "loop_start_seconds": 200.0,
                "loop_end_seconds": 215.0,
                "loop_repeats": 2,
                "next_track_id": "t2",
            }],
        }
        temp_dir = _preprocess_loops(plan, config)
        assert temp_dir is not None
        assert mock_create.called
        # Cleanup
        cleanup_temp_loops(temp_dir)

    @patch("autodj.render.render.create_loop_hold")
    def test_loop_hold_failure_falls_back(self, mock_create, config):
        """Failed loop extraction falls back to bass_swap."""
        mock_create.return_value = False
        plan = {
            "transitions": [{
                "track_index": 0,
                "file_path": "/music/track.mp3",
                "bpm": 128.0,
                "transition_type": "loop_hold",
                "loop_start_seconds": 200.0,
                "loop_end_seconds": 215.0,
                "loop_repeats": 2,
                "next_track_id": "t2",
            }],
        }
        temp_dir = _preprocess_loops(plan, config)
        # Should have fallen back to bass_swap
        assert plan["transitions"][0]["transition_type"] == "bass_swap"
        if temp_dir:
            cleanup_temp_loops(temp_dir)


class TestLegacyAlias:
    """Verify backward compatibility of function aliasing."""

    def test_alias_produces_same_output(self, sample_plan, config):
        """_generate_liquidsoap_script is an alias for _generate_liquidsoap_script_legacy."""
        script1 = _generate_liquidsoap_script(sample_plan, "/tmp/mix.mp3", config)
        script2 = _generate_liquidsoap_script_legacy(sample_plan, "/tmp/mix.mp3", config)
        assert script1 == script2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
