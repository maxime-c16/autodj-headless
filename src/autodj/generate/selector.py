"""
Track Selector: Greedy algorithm for playlist generation.

Per SPEC.md § 5.2 and § 2.2:
- Greedy graph traversal (no backtracking or branch-and-bound)
- Constraints:
  - BPM within ±4% (±5 BPM @ 126 BPM)
  - Camelot-compatible harmonic key
  - Energy continuity
  - No track repeats
- Output: Ordered list of track IDs
"""

import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class SelectionConstraints:
    """Track selection constraints from config."""

    def __init__(self, config: dict):
        """
        Args:
            config: Constraints dict from config["constraints"]
        """
        self.bpm_tolerance = config.get("bpm_tolerance_percent", 4.0)
        self.energy_window = config.get("energy_window_size", 3)
        self.min_duration = config.get("min_track_duration_seconds", 120)
        self.max_repeat_decay = config.get("max_repeat_decay_hours", 168)


def select_playlist(
    library: Dict[str, Any],
    seed_track_id: int,
    target_duration_minutes: int,
    constraints: SelectionConstraints,
) -> Optional[List[int]]:
    """
    Generate a playlist using greedy graph traversal.

    Args:
        library: Track metadata dict (loaded from SQLite)
        seed_track_id: Starting track ID
        target_duration_minutes: Target mix duration
        constraints: SelectionConstraints object

    Returns:
        List of track IDs in playback order, or None if generation failed
    """
    # TODO: Implement greedy selector
    # 1. Start with seed track
    # 2. For each position in playlist:
    #    - Find candidates matching constraints
    #    - Pick best candidate (greedy: high energy similarity)
    #    - Add to playlist
    #    - Mark as "used in this set" (decay_hours)
    # 3. Stop when duration >= target
    # 4. Return track ID list

    logger.warning("Track selector not yet implemented")
    return None
