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
    try:
        # Load transitions plan
        with open(transitions_json_path, "r") as f:
            plan = json.load(f)

        # Generate Liquidsoap script
        script = _generate_liquidsoap_script(plan, output_path, config)

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".liq", mode="w", delete=False
        ) as tmp:
            tmp.write(script)
            script_path = tmp.name

        # Execute Liquidsoap
        logger.info(f"Starting Liquidsoap render: {output_path}")
        result = subprocess.run(
            ["liquidsoap", script_path],
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Liquidsoap failed: {result.stderr}")
            return False

        logger.info(f"Render complete: {output_path}")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Render timeout after {timeout_seconds} seconds")
        return False
    except Exception as e:
        logger.error(f"Render failed: {e}")
        return False


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

    # ==================== HELPER FUNCTIONS ====================
    script.append("# Load track with cue points")
    script.append('def load_track(path, cue_start_s, cue_end_s, target_bpm) =')
    script.append("  # Load audio file")
    script.append('  audio = ffmpeg.decode(path)')
    script.append("")
    script.append("  # Extract cue region if specified")
    script.append("  if cue_start_s > 0.0 then")
    script.append('    audio = source.skip(audio, cue_start_s)')
    script.append("  end")
    script.append("")
    script.append("  if cue_end_s > cue_start_s then")
    script.append('    duration = cue_end_s - cue_start_s')
    script.append('    audio = source.duration(audio, duration)')
    script.append("  end")
    script.append("")
    script.append("  audio")
    script.append("end")
    script.append("")

    # ==================== SEQUENCE BUILD ====================
    script.append("# Build mix sequence")
    script.append("tracks = [")

    for idx, trans in enumerate(transitions):
        track_id = trans.get("track_id")
        file_path = trans.get("file_path", "")
        entry_cue = trans.get("entry_cue", "cue_in")
        exit_cue = trans.get("exit_cue", "cue_out")
        hold_duration_bars = trans.get("hold_duration_bars", 16)
        target_bpm = trans.get("target_bpm", 120.0)
        mix_out_seconds = trans.get("mix_out_seconds", 4.0)

        # Estimate cue times (placeholder, would need actual analysis)
        # For now, use full track duration minus small margins
        cue_start_s = 0.0
        cue_end_s = 0.0  # 0 = full duration

        script.append(f"  # Track {idx + 1}: {track_id}")
        script.append(f'  load_track("{file_path}", {cue_start_s}, {cue_end_s}, {target_bpm}),')

    script.append("]")
    script.append("")

    # ==================== MIXING ====================
    script.append("# Concatenate tracks with crossfade")
    script.append("mix = sequence(tracks)")
    script.append("")
    script.append(f"# Apply crossfade between tracks ({crossfade_duration}s)")
    script.append(f'mix = smart_crossfade(mix, duration={crossfade_duration})')
    script.append("")

    # ==================== OUTPUT ====================
    script.append("# Encode output")
    if output_format == "mp3":
        script.append(
            f'output.file(format(%%mp3(bitrate={mp3_bitrate}, stereo=true)), "{output_path}", mix)'
        )
    elif output_format == "flac":
        script.append(f'output.file(format(%%flac), "{output_path}", mix)')
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(format(%%mp3(bitrate={mp3_bitrate}, stereo=true)), "{output_path}", mix)'
        )

    script.append("")

    return "\n".join(script)


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

            result = subprocess.run(
                ["liquidsoap", script_path],
                timeout=timeout_seconds,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"Liquidsoap failed: {result.stderr}")
                logger.debug(f"Script stdout: {result.stdout}")
                return False

            logger.info(f"✅ Render complete: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Render timeout after {timeout_seconds} seconds")
            return False
        except Exception as e:
            logger.error(f"Render failed: {e}")
            return False
        finally:
            # Cleanup temp script
            try:
                Path(script_path).unlink()
            except:
                pass
