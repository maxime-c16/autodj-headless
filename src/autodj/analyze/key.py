"""
Key Detection using essentia or keyfinder-cli.

Per SPEC.md § 5.1:
- Uses essentia-streaming or keyfinder-cli subprocess
- Budget: ≤ 200 MiB peak memory (essentia) or ≤ 100 MiB (keyfinder)
- Single file at a time
- Output: Camelot notation (1A, 1B, ..., 12B)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def detect_key(audio_path: str, config: dict) -> Optional[str]:
    """
    Detect musical key from audio file.

    Args:
        audio_path: Path to audio file
        config: Key detection config dict (method, window_size)

    Returns:
        Key in Camelot notation (e.g., "9A", "1B") or None if detection failed
    """
    # TODO: Implement key detection
    # - Use method specified in config["key_detection"]["method"]
    #   - "essentia": essentia-streaming library
    #   - "keyfinder-cli": subprocess call to keyfinder-cli
    # - Return Camelot notation (1A-12B)
    # - Handle errors gracefully (mark as "unknown" in DB)

    logger.warning("Key detection not yet implemented")
    return None
