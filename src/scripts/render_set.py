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
from autodj.render.render import render

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

        # Find matching m3u file (same timestamp prefix)
        stem = latest_transitions.stem.replace(".transitions", "")
        m3u_files = list(playlists_dir.glob(f"{stem}*.m3u"))

        if not m3u_files:
            logger.warning(f"No matching M3U file found for {stem}")
            latest_m3u = None
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

        # Render
        start_time = time.time()
        logger.info("Starting Liquidsoap rendering...")

        success = render(
            transitions_json_path=str(latest_transitions),
            output_path=str(output_path),
            config=config.data,  # Pass underlying dict, not Config object
            timeout_seconds=config["render"].get("timeout_seconds", 420),
        )

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
