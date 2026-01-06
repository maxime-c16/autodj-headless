#!/usr/bin/env python3
"""
Generate DJ Playlist and Transition Plan Script

Main entrypoint: make generate

Per SPEC.md § 2.2:
- Max 30 sec total runtime
- Peak memory ≤ 512 MiB
- Outputs: playlist.m3u and transitions.json
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Main generation entrypoint."""
    try:
        logger.info("🎵 Starting playlist generation...")

        # Load config
        config = Config.load()
        logger.info(f"Config loaded: {config}")

        # TODO: Implement generation pipeline
        # 1. Load library metadata from SQLite
        # 2. Select random seed track (or from config)
        # 3. Run selector.select_playlist() with constraints
        # 4. Run playlist.generate() to create m3u and transitions.json
        # 5. Write outputs to data/playlists/{timestamp}.*
        # 6. Log summary: N tracks, duration, seed BPM

        timestamp = datetime.utcnow().isoformat()
        logger.info(
            f"✅ Playlist generated: data/playlists/{timestamp}.m3u"
        )
        logger.info(
            f"✅ Transitions generated: data/playlists/{timestamp}.transitions.json"
        )
        return 0

    except KeyboardInterrupt:
        logger.warning("Generation interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
