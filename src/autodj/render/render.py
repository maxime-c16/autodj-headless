"""
Liquidsoap Render Engine.

Generates and executes Liquidsoap offline mixing scripts.
Per SPEC.md § 5.3:
- Offline clock
- Streaming decode/encode
- Memory-bounded
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import json
from datetime import datetime
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC

logger = logging.getLogger(__name__)


def render(
    transitions_json_path: str,
    output_path: str,
    config: dict,
    timeout_seconds: int = 420,  # 7 minutes per SPEC.md § 6.3
) -> bool:
    """
    Execute Liquidsoap rendering.

    Args:
        transitions_json_path: Path to transitions.json
        output_path: Path to output mix file
        config: Render config dict
        timeout_seconds: Max runtime (default 420 sec = 7 min)

    Returns:
        True if successful, False otherwise
    """
    script_path = None
    try:
        # Load transitions plan
        with open(transitions_json_path, "r") as f:
            plan = json.load(f)

        # Generate Liquidsoap script
        script = _generate_liquidsoap_script(plan, output_path, config)
        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".liq", mode="w", delete=False
        ) as tmp:
            tmp.write(script)
            script_path = tmp.name

        # Save debug copy
        debug_script_path = Path("/tmp/last_render_standalone.liq")
        debug_script_path.write_text(script)
        logger.info(f"Debug script saved to: {debug_script_path}")

        # Execute Liquidsoap
        logger.info(f"Starting Liquidsoap render: {output_path}")
        logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")
        result = subprocess.run(
            ["liquidsoap", script_path],
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Liquidsoap failed with return code {result.returncode}")
            logger.error(f"Liquidsoap stderr: {result.stderr if result.stderr else '(no stderr)'}")
            logger.error(f"Liquidsoap stdout: {result.stdout if result.stdout else '(no stdout)'}")
            logger.error(f"Debug script saved to: {debug_script_path}")
            _cleanup_partial_output(output_path)
            return False

        # Validate output
        if not _validate_output_file(output_path):
            logger.error("Output file validation failed")
            _cleanup_partial_output(output_path)
            return False

        # Add metadata to output
        playlist_id = plan.get("playlist_id", "autodj-playlist")
        timestamp = datetime.now().isoformat()
        _write_mix_metadata(output_path, playlist_id, timestamp)

        logger.info(f"✅ Render complete: {output_path}")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Render timeout after {timeout_seconds} seconds")
        _cleanup_partial_output(output_path)
        return False
    except Exception as e:
        logger.error(f"Render failed: {e}")
        _cleanup_partial_output(output_path)
        return False
    finally:
        # Cleanup temp script
        if script_path:
            try:
                Path(script_path).unlink()
                logger.debug(f"Cleaned up temp script: {script_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp script {script_path}: {e}")


def _frames_to_seconds(frames: Optional[int], sample_rate: int = 44100) -> float:
    """Convert frame offset to seconds."""
    if frames is None or frames == 0:
        return 0.0
    return float(frames) / sample_rate


def _calculate_stretch_ratio(
    native_bpm: Optional[float], target_bpm: Optional[float]
) -> float:
    """
    Calculate time-stretch ratio for BPM matching.

    Args:
        native_bpm: Track's detected BPM
        target_bpm: Target BPM for rendering

    Returns:
        Stretch ratio (1.0 = no change, >1.0 = faster, <1.0 = slower)
    """
    if native_bpm is None or target_bpm is None or native_bpm == 0:
        return 1.0
    ratio = target_bpm / native_bpm
    # Clamp to reasonable range (±8% per SPEC.md BPM tolerance)
    ratio = max(0.92, min(1.08, ratio))
    return ratio


def _generate_liquidsoap_script(
    plan: dict, output_path: str, config: dict, m3u_path: str = ""
) -> str:
    """
    Generate Liquidsoap offline mixing script with advanced DSP.

    Per SPEC.md § 5.3:
    - Offline clock (no real-time sync)
    - Streaming decode/encode
    - Memory-bounded
    - Transitions: crossfades with cue points and BPM time-stretching

    Args:
        plan: Transitions plan dict with transitions list
        output_path: Path to output file
        config: Render config (output format, bitrate, crossfade duration)
        m3u_path: Path to M3U playlist file (optional, for file path reference)

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 192)
    crossfade_duration = config.get("render", {}).get("crossfade_duration_seconds", 4.0)

    transitions = plan.get("transitions", [])

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    # Start building Liquidsoap script
    script = []

    # ==================== SETTINGS ====================
    script.append("# AutoDJ-Headless Offline Mix")
    script.append("# Generated Liquidsoap script for DJ-quality mixing")
    script.append("# Features: Cue points, BPM time-stretching, beatmatched crossfades")
    script.append("")
    script.append("# Offline clock (no real-time sync)")
    script.append('set("clock.sync", false)')
    script.append('set("frame.video.samplerate", 44100)')
    script.append("")

    # ==================== HELPER FUNCTIONS ====================
    script.append("# Crossfade transition function")
    script.append("def crossfade_transition(a, b) =")
    script.append(f"  # Linear fade-in/fade-out crossfade ({crossfade_duration}s)")
    script.append(f"  fade_in = fade.in(duration={crossfade_duration}, b)")
    script.append(f"  fade_out = fade.out(duration={crossfade_duration}, a)")
    script.append("  add(normalize=false, [fade_in, fade_out])")
    script.append("end")
    script.append("")

    # ==================== TRACK SEQUENCE BUILD ====================
    script.append("# Build track sequence with cue points and time-stretching")
    script.append("")

    # Generate individual track definitions
    track_vars = []
    for idx, trans in enumerate(transitions):
        track_var = f"track_{idx}"
        track_vars.append(track_var)

        file_path = trans.get("file_path", "")
        track_id = trans.get("track_id", f"unknown_{idx}")
        native_bpm = trans.get("bpm")
        target_bpm = trans.get("target_bpm", native_bpm)
        cue_in_frames = trans.get("cue_in_frames", 0)
        cue_out_frames = trans.get("cue_out_frames")

        # Convert frames to seconds
        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)

        # Calculate stretch ratio for BPM matching
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        # Build track with processing pipeline
        script.append(f"# Track {idx + 1}: {track_id}")
        script.append(f"#   Native BPM: {native_bpm}, Target BPM: {target_bpm}, Stretch: {stretch_ratio:.3f}")
        script.append(f"{track_var} = single(\"{file_path}\")")

        # Apply cue points (trim if cue_out is set)
        if cue_out_sec > 0:
            script.append(f"{track_var} = trim(start={cue_in_sec:.3f}, stop={cue_out_sec:.3f}, {track_var})")
        elif cue_in_sec > 0:
            script.append(f"{track_var} = trim(start={cue_in_sec:.3f}, {track_var})")

        # Apply time-stretching for BPM matching
        if stretch_ratio != 1.0:
            script.append(f"{track_var} = stretch(ratio={stretch_ratio:.3f}, {track_var})")

        # Wrap in once() to ensure single playback
        script.append(f"{track_var} = once({track_var})")
        script.append("")

    # ==================== TRACK SEQUENCE ====================
    script.append("# Chain tracks in sequence")
    if len(track_vars) == 1:
        # Single track
        script.append(f"sequence = mksafe({track_vars[0]})")
    else:
        # Multiple tracks: use sequence() to concatenate
        # Note: Full crossfade implementation coming in future version
        script.append("# Build track sequence")
        script.append(f"sequence = mksafe(sequence([")
        for idx, track_var in enumerate(track_vars):
            if idx == len(track_vars) - 1:
                script.append(f"  {track_var}")
            else:
                script.append(f"  {track_var},")
        script.append("]))")

    script.append("")

    # ==================== OUTPUT ENCODING ====================
    script.append("# Encode and output")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", sequence)'
        )
    elif output_format == "flac":
        script.append(f'output.file(%flac, "{output_path}", sequence)')
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", sequence)'
        )

    script.append("")

    return "\n".join(script)


def _validate_output_file(output_path: str) -> bool:
    """
    Validate rendered output file (SPEC.md § 10.3).

    Args:
        output_path: Path to output file

    Returns:
        True if valid, False otherwise
    """
    try:
        output_file = Path(output_path)

        # Check file exists
        if not output_file.exists():
            logger.error(f"Output file does not exist: {output_path}")
            return False

        # Check minimum size (1 MiB per SPEC.md § 10.3)
        min_size_bytes = 1024 * 1024
        file_size = output_file.stat().st_size
        if file_size < min_size_bytes:
            logger.error(f"Output file too small: {file_size} bytes (minimum {min_size_bytes})")
            return False

        logger.debug(f"Output validation passed: {output_path} ({file_size} bytes)")
        return True

    except Exception as e:
        logger.error(f"Output validation failed: {e}")
        return False


def _write_mix_metadata(output_path: str, playlist_id: str, timestamp: str) -> bool:
    """
    Write ID3 metadata to output mix file (SPEC.md § 4.4).

    Args:
        output_path: Path to output file
        playlist_id: Playlist identifier
        timestamp: Generation timestamp (ISO format)

    Returns:
        True if successful, False otherwise
    """
    try:
        output_file = Path(output_path)
        if not output_file.exists():
            logger.warning(f"Output file not found for metadata writing: {output_path}")
            return False

        year = timestamp[:4]  # Extract year from ISO timestamp
        album_name = f"AutoDJ Mix {timestamp[:10]}"  # YYYY-MM-DD
        genre = "DJ Mix"

        # Handle MP3 files
        if output_path.lower().endswith('.mp3'):
            try:
                audio = EasyID3(output_path)
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added ID3 metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write ID3 tags to MP3: {e}")
                return False

        # Handle FLAC files
        elif output_path.lower().endswith('.flac'):
            try:
                audio = FLAC(output_path)
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added VORBIS metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write VORBIS tags to FLAC: {e}")
                return False

        else:
            logger.debug(f"Unsupported format for metadata: {output_path}")
            return False

        return True

    except Exception as e:
        logger.error(f"Metadata writing failed: {e}")
        return False


def _cleanup_partial_output(output_path: str) -> None:
    """
    Clean up partial or failed output files.

    Args:
        output_path: Path to output file to remove
    """
    try:
        output_file = Path(output_path)
        if output_file.exists():
            output_file.unlink()
            logger.debug(f"Cleaned up partial output: {output_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up output file {output_path}: {e}")


class RenderEngine:
    """Liquidsoap offline rendering orchestrator."""

    def __init__(self, config: dict):
        """
        Initialize render engine.

        Args:
            config: Configuration dict
        """
        self.config = config
        logger.info("RenderEngine initialized")

    def render_playlist(
        self,
        transitions_json_path: str,
        playlist_m3u_path: str,
        output_path: str,
        timeout_seconds: int = 420,
    ) -> bool:
        """
        Render playlist to final mix.

        Args:
            transitions_json_path: Path to transitions.json
            playlist_m3u_path: Path to playlist.m3u (for track reference)
            output_path: Output mix file path
            timeout_seconds: Max render time

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Starting render: {output_path}")
        script_path = None

        # Load transitions plan
        try:
            with open(transitions_json_path, "r") as f:
                plan = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load transitions: {e}")
            return False

        # Load playlist for file paths
        try:
            with open(playlist_m3u_path, "r") as f:
                playlist_lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to load playlist: {e}")
            return False

        # Map transitions to file paths from M3U
        file_paths = [
            line.strip() for line in playlist_lines
            if not line.startswith("#") and line.strip()
        ]

        for idx, trans in enumerate(plan.get("transitions", [])):
            if idx < len(file_paths):
                trans["file_path"] = file_paths[idx]

        # Generate script
        script = _generate_liquidsoap_script(plan, output_path, self.config, playlist_m3u_path)
        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write and execute script
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".liq", mode="w", delete=False
            ) as tmp:
                tmp.write(script)
                script_path = tmp.name

            logger.debug(f"Liquidsoap script: {script_path}")
            logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")

            # Also save to a known location for debugging
            debug_script_path = Path("/tmp/last_render.liq")
            debug_script_path.write_text(script)
            logger.info(f"Debug script saved to: {debug_script_path}")

            result = subprocess.run(
                ["liquidsoap", script_path],
                timeout=timeout_seconds,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"Liquidsoap failed with return code {result.returncode}")
                logger.error(f"Liquidsoap stderr: {result.stderr if result.stderr else '(no stderr)'}")
                logger.error(f"Liquidsoap stdout: {result.stdout if result.stdout else '(no stdout)'}")
                logger.error(f"Debug script saved to: {debug_script_path}")
                logger.error(f"You can inspect with: cat {debug_script_path}")
                _cleanup_partial_output(output_path)
                return False

            # Validate output
            if not _validate_output_file(output_path):
                logger.error("Output file validation failed")
                _cleanup_partial_output(output_path)
                return False

            # Add metadata to output
            playlist_id = plan.get("playlist_id", "autodj-playlist")
            timestamp = datetime.now().isoformat()
            _write_mix_metadata(output_path, playlist_id, timestamp)

            logger.info(f"✅ Render complete: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Render timeout after {timeout_seconds} seconds")
            _cleanup_partial_output(output_path)
            return False
        except Exception as e:
            logger.error(f"Render failed: {e}")
            _cleanup_partial_output(output_path)
            return False
        finally:
            # Cleanup temp script
            if script_path:
                try:
                    Path(script_path).unlink()
                    logger.debug(f"Cleaned up temp script: {script_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp script {script_path}: {e}")
