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
from typing import List, Optional, Dict, Any, Set
from datetime import datetime, timezone, timedelta

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


class MerlinGreedySelector:
    """
    Greedy track selector (Merlin).

    Implements deterministic greedy graph traversal for playlist generation.
    No backtracking; pick the "best available" track at each step.
    """

    def __init__(self, database, constraints: SelectionConstraints):
        """
        Initialize selector with database connection and constraints.

        Args:
            database: Database object with track metadata
            constraints: SelectionConstraints object
        """
        self.db = database
        self.constraints = constraints
        self.used_in_set: Set[str] = set()
        logger.info("MerlinGreedySelector initialized")

    @staticmethod
    def _camelot_compatible(key1: Optional[str], key2: Optional[str]) -> bool:
        """
        Check if two keys are harmonically compatible in Camelot notation.

        Compatible keys are:
        - Same key (e.g., 8B and 8B)
        - Adjacent on the wheel (e.g., 8B and 9B)
        - Same number, opposite mode (e.g., 8B and 8A)

        Args:
            key1: First Camelot key (e.g., "8B")
            key2: Second Camelot key (e.g., "9B")

        Returns:
            True if keys are compatible, False otherwise
        """
        if key1 is None or key2 is None or key1 == "unknown" or key2 == "unknown":
            # If either key is unknown, consider it compatible (no constraint)
            return True

        try:
            # Parse keys (format: "8B" -> number=8, mode="B")
            num1, mode1 = int(key1[:-1]), key1[-1]
            num2, mode2 = int(key2[:-1]), key2[-1]

            # Same mode check
            if mode1 != mode2:
                # Different modes must be same number (parallel key)
                return num1 == num2

            # Same mode: check if adjacent on the wheel
            # Camelot wheel: keys are numbered 1-12 (circular)
            if num1 == num2:
                return True  # Exact match

            # Adjacent keys (with wrapping)
            adjacent = (num1 % 12) + 1 == (num2 % 12) or (num2 % 12) + 1 == (num1 % 12)
            return adjacent

        except (ValueError, IndexError):
            # Malformed key, treat as compatible (no constraint)
            logger.debug(f"Malformed key: {key1} or {key2}, allowing compatibility")
            return True

    @staticmethod
    def _bpm_compatible(bpm1: Optional[float], bpm2: Optional[float], tolerance_percent: float) -> bool:
        """
        Check if two BPMs are within tolerance.

        Args:
            bpm1: First BPM (or None)
            bpm2: Second BPM (or None)
            tolerance_percent: Tolerance as percentage (e.g., 4.0 for ±4%)

        Returns:
            True if compatible, False otherwise
        """
        if bpm1 is None or bpm2 is None:
            # Missing BPM data, allow it
            return True

        # Calculate tolerance range
        tolerance_bpm = bpm1 * (tolerance_percent / 100.0)
        return abs(bpm2 - bpm1) <= tolerance_bpm

    def _is_recently_used(self, track_id: str, hours_back: int) -> bool:
        """
        Check if track was recently used (within decay window).

        Args:
            track_id: Track ID to check
            hours_back: Look back window in hours

        Returns:
            True if track was used recently, False otherwise
        """
        recent = self.db.get_recent_usage(track_id, hours_back=hours_back)
        return len(recent) > 0

    def choose_next(
        self,
        current_track: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[tuple]:
        """
        Choose the next track using greedy heuristics.

        Greedy criteria (in order):
        1. Harmonic compatibility (Camelot key)
        2. BPM compatibility
        3. No recent usage (decay window)
        4. Lowest distance from current energy

        Args:
            current_track: Current track metadata dict
            candidates: List of candidate track dicts

        Returns:
            Tuple (track_id, hints) where hints is a dict with scoring info,
            or None if no valid candidate found
        """
        valid_candidates = []

        for candidate in candidates:
            track_id = candidate.get("id")
            if track_id in self.used_in_set:
                continue  # Already used in this set

            if self._is_recently_used(track_id, self.constraints.max_repeat_decay):
                logger.debug(f"Track {track_id} recently used; skipping")
                continue

            # Check BPM compatibility
            if not self._bpm_compatible(
                current_track.get("bpm"),
                candidate.get("bpm"),
                self.constraints.bpm_tolerance,
            ):
                logger.debug(
                    f"Track {track_id} BPM {candidate.get('bpm')} "
                    f"incompatible with {current_track.get('bpm')}"
                )
                continue

            # Check harmonic compatibility
            if not self._camelot_compatible(current_track.get("key"), candidate.get("key")):
                logger.debug(
                    f"Track {track_id} key {candidate.get('key')} "
                    f"incompatible with {current_track.get('key')}"
                )
                continue

            # Valid candidate
            valid_candidates.append(candidate)

        if not valid_candidates:
            logger.debug("No valid candidates found")
            return None

        # Greedy pick: prefer high harmonic match, lower energy deviation
        # For now, pick the first valid candidate (deterministic, simple)
        # In future: sort by energy distance or harmonic score
        chosen = valid_candidates[0]
        track_id = chosen.get("id")

        self.used_in_set.add(track_id)

        hints = {
            "bpm": chosen.get("bpm"),
            "key": chosen.get("key"),
            "valid_count": len(valid_candidates),
        }

        logger.debug(
            f"Chose track {track_id} "
            f"(BPM: {chosen.get('bpm')}, Key: {chosen.get('key')}, "
            f"Valid: {len(valid_candidates)})"
        )

        return (track_id, hints)

    def build_playlist(
        self,
        library: List[Dict[str, Any]],
        seed_track_id: str,
        target_duration_minutes: int,
        max_tracks: int = 90,
    ) -> Optional[List[str]]:
        """
        Build a playlist starting from seed track.

        Args:
            library: List of track metadata dicts
            seed_track_id: Starting track ID
            target_duration_minutes: Target mix duration
            max_tracks: Maximum number of tracks

        Returns:
            List of track IDs in order, or None if generation failed
        """
        # Build lookup dict for fast access
        track_dict = {t.get("id"): t for t in library}

        if seed_track_id not in track_dict:
            logger.error(f"Seed track {seed_track_id} not found in library")
            return None

        seed_track = track_dict[seed_track_id]
        playlist = [seed_track_id]
        total_duration = seed_track.get("duration_seconds", 0)
        target_duration_seconds = target_duration_minutes * 60

        self.used_in_set.add(seed_track_id)

        logger.info(
            f"Building playlist from seed {seed_track_id} "
            f"(target: {target_duration_minutes}min = {target_duration_seconds}s)"
        )

        current_track = seed_track
        iteration = 1

        # Greedy loop: keep adding tracks until we reach target duration
        while total_duration < target_duration_seconds and len(playlist) < max_tracks:
            # Get remaining candidates
            candidates = [
                t for t in library
                if t.get("id") not in self.used_in_set
                and t.get("duration_seconds", 0) >= self.constraints.min_duration
            ]

            if not candidates:
                logger.warning("No more valid candidates")
                break

            result = self.choose_next(current_track, candidates)
            if result is None:
                logger.warning("No compatible next track found")
                break

            next_track_id, hints = result
            next_track = track_dict[next_track_id]

            playlist.append(next_track_id)
            total_duration += next_track.get("duration_seconds", 0)

            logger.debug(
                f"Iteration {iteration}: added {next_track_id} "
                f"(duration: {next_track.get('duration_seconds')}s, "
                f"total: {total_duration}s)"
            )

            current_track = next_track
            iteration += 1

        logger.info(
            f"✅ Playlist built: {len(playlist)} tracks, "
            f"{total_duration}s ({total_duration/60:.1f}min)"
        )

        return playlist


def select_playlist(
    library: Dict[str, Any],
    seed_track_id: str,
    target_duration_minutes: int,
    constraints: SelectionConstraints,
    database=None,
) -> Optional[List[str]]:
    """
    Generate a playlist using greedy graph traversal (Merlin selector).

    Args:
        library: List of track metadata dicts (from database)
        seed_track_id: Starting track ID
        target_duration_minutes: Target mix duration in minutes
        constraints: SelectionConstraints object
        database: Database connection (for repeat decay checks)

    Returns:
        List of track IDs in playback order, or None if generation failed
    """
    selector = MerlinGreedySelector(database, constraints)
    return selector.build_playlist(library, seed_track_id, target_duration_minutes)
