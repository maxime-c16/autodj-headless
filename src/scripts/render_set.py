#!/usr/bin/env python3
"""
Render DJ Mix Script

Main entrypoint: make render

Per SPEC.md § 2.3:
- Max 7 min for 60-min mix
- Peak memory ≤ 512 MiB
- Outputs: MP3 or FLAC mix file
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import time

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.config import Config
from autodj.render.render import render, render_segmented
from autodj.render.progress import get_progress_tracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Main rendering entrypoint."""
    try:
        logger.info("🎚️  Starting mix rendering...")

        # Load config
        config = Config.load()
        logger.debug("Config loaded successfully")

        # Find latest transitions.json
        playlists_dir = Path(config["system"]["playlists_path"])

        if not playlists_dir.exists():
            logger.error(f"Playlists directory not found: {playlists_dir}")
            return 1

        # Find all transitions.json files (sorted by modification time, newest first)
        transition_files = sorted(
            playlists_dir.glob("*transitions*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not transition_files:
            logger.error(f"No transitions.json found in {playlists_dir}")
            return 1

        latest_transitions = transition_files[0]
        logger.info(f"Found latest transitions: {latest_transitions}")

        # Find matching m3u file (same timestamp as transitions)
        # transitions filename: transitions-<ts>.json -> playlist filename: playlist-<ts>.m3u
        ts = latest_transitions.name.replace("transitions-", "").replace(".json", "")
        expected_name = f"playlist-{ts}"
        m3u_files = list(playlists_dir.glob(f"{expected_name}*.m3u"))

        if not m3u_files:
            logger.warning(f"No matching M3U file found for {latest_transitions.name}; attempting fallback to newest M3U")
            m3u_candidates = sorted(playlists_dir.glob("*.m3u"), key=lambda p: p.stat().st_mtime, reverse=True)
            latest_m3u = m3u_candidates[0] if m3u_candidates else None
            if latest_m3u:
                logger.info(f"Falling back to newest playlist: {latest_m3u}")
            else:
                logger.warning(f"No M3U files available in {playlists_dir}")
        else:
            latest_m3u = m3u_files[0]
            logger.info(f"Found matching playlist: {latest_m3u}")

        # Prepare output directory
        mixes_dir = Path(config["system"]["mixes_path"])
        mixes_dir.mkdir(parents=True, exist_ok=True)

        # Generate output filename with timestamp
        timestamp = datetime.utcnow().isoformat().replace(":", "-")
        output_format = config["render"]["output_format"]
        output_path = mixes_dir / f"{timestamp}.{output_format}"

        # Log render parameters
        logger.info(f"Output format: {output_format}")
        logger.info(f"Output bitrate: {config['render'].get('mp3_bitrate', 192)} kbps")
        logger.info(f"Crossfade duration: {config['render'].get('crossfade_duration_seconds', 4)} sec")
        logger.info(f"Rendering to: {output_path}")

        # Load transitions to determine segment count
        import json
        with open(latest_transitions) as f:
            plan = json.load(f)
        num_tracks = len(plan.get("transitions", []))

        # Create progress tracker
        max_tracks_before_segment = config["render"].get("max_tracks_before_segment", 10)
        enable_progress_display = config["render"].get("enable_progress_display", True)
        total_segments = 1  # Will be determined if segmented

        # Estimate segment count
        if num_tracks > max_tracks_before_segment:
            segment_size = config["render"].get("segment_size", 5)
            total_segments = (num_tracks + segment_size - 1) // segment_size

        tracker = get_progress_tracker(
            total_tracks=num_tracks,
            total_segments=total_segments,
            interactive=enable_progress_display,
        )
        tracker.set_output_path(str(output_path))

        # Define progress callback
        def progress_callback(segment_idx, total_segs, status):
            if status == "rendering":
                tracker.start_segment(segment_idx, 5)  # Approximate tracks per segment
            elif status == "completed":
                tracker.complete_segment(segment_idx)
            elif status == "concatenating":
                logger.info("Concatenating segments...")

        # Render with segmentation support
        start_time = time.time()
        logger.info("Starting Liquidsoap rendering...")

        success = render_segmented(
            transitions_json_path=str(latest_transitions),
            output_path=str(output_path),
            config=config.data,  # Pass underlying dict, not Config object
            progress_callback=progress_callback if enable_progress_display else None,
        )

        # Mark progress as complete
        if enable_progress_display:
            tracker.complete_concatenation()

        elapsed_time = time.time() - start_time

        if not success:
            logger.error("Rendering failed")
            return 1

        # Log stats
        if output_path.exists():
            file_size_bytes = output_path.stat().st_size
            file_size_mb = file_size_bytes / (1024 * 1024)
            file_size_kb = file_size_bytes / 1024

            logger.info(f"✅ Mix rendered: {output_path}")
            logger.info(f"📊 SUMMARY:")
            logger.info(f"   File size: {file_size_mb:.2f} MiB ({file_size_kb:.0f} KB)")
            logger.info(f"   Render time: {elapsed_time:.1f} seconds")
            if elapsed_time > 0:
                logger.info(f"   Render speed: {elapsed_time / 60:.1f}x real-time")
        else:
            logger.error(f"Output file not created: {output_path}")
            return 1

        return 0

    except KeyboardInterrupt:
        logger.warning("Rendering interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Rendering failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
