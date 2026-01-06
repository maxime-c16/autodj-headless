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


def _generate_liquidsoap_script(
    plan: dict, output_path: str, config: dict
) -> str:
    """
    Generate Liquidsoap offline mixing script.

    Per SPEC.md § 5.3:
    - Offline clock (no real-time sync)
    - Streaming decode/encode
    - Memory-bounded
    - Transitions: smart_crossfade with optional effects

    Args:
        plan: Transitions plan dict
        output_path: Path to output file
        config: Render config

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 192)
    time_stretch_quality = config.get("render", {}).get("time_stretch_quality", "high")

    transitions = plan.get("transitions", [])
    crossfade_duration = config.get("render", {}).get("crossfade_duration_seconds", 4.0)

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    # Start building Liquidsoap script
    script = []

    # ==================== SETTINGS ====================
    script.append("# AutoDJ-Headless Offline Mix")
    script.append("# Generated Liquidsoap script for offline rendering")
    script.append("")
    script.append("# Offline clock (no real-time sync)")
    script.append('set("clock.sync", false)')
    script.append("")

    # ==================== SEQUENCE BUILD ====================
    script.append("# Decode all tracks with ffmpeg")

    for idx, trans in enumerate(transitions):
        track_id = trans.get("track_id")
        file_path = trans.get("file_path", "")
        target_bpm = trans.get("target_bpm", 120.0)

        script.append(f"# Track {idx + 1}: {track_id}")
        script.append(f'track{idx+1} = input.ffmpeg("{file_path}")')

    script.append("")
    script.append("# Build mix sequence")
    script.append("tracks = [")
    for idx in range(len(transitions)):
        script.append(f"  track{idx+1},")
    script.append("]")
    script.append("")

    # ==================== MIXING ====================
    script.append("# Concatenate tracks with crossfade")
    script.append("mix = sequence(tracks)")
    script.append("")
    script.append(f"# Apply crossfade between tracks ({crossfade_duration}s)")
    script.append(f'mix = crossfade(mix, duration={crossfade_duration})')
    script.append("")

    # ==================== OUTPUT ====================
    script.append("# Encode output")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", mix)'
        )
    elif output_format == "flac":
        script.append(f'output.file(%flac, "{output_path}", mix)')
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", mix)'
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
        script = _generate_liquidsoap_script(plan, output_path, self.config)
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
