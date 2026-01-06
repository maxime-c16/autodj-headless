"""
BPM Detection using aubio.

Per SPEC.md § 5.1:
- Uses aubio streaming mode
- Budget: ≤ 150 MiB peak memory
- Single file at a time
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def detect_bpm(audio_path: str, config: dict) -> Optional[float]:
    """
    Detect BPM from audio file.

    Args:
        audio_path: Path to audio file
        config: Analysis config dict

    Returns:
        BPM value (float, range 50-200) or None if detection failed
    """
    # TODO: Implement aubio-based BPM detection
    # - Load audio via aubio (streaming, low memory)
    # - Detect onset detection -> BPM estimation
    # - Validate against config["analysis"]["bpm_search_range"]
    # - Return float or None

    logger.warning("BPM detection not yet implemented")
    return None
