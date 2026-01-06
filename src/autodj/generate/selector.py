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


class BlastxcssSelector(MerlinGreedySelector):
    """
    High-energy specialized selector (Blastxcss).

    Extends Merlin with high-energy heuristics:
    - Prefers high-energy tracks
    - Builds energy curve: intro → build → peak → comedown
    - Targets peak energy at mix midpoint
    - May relax BPM constraints slightly for energy continuity
    """

    def __init__(self, database, constraints: SelectionConstraints):
        """Initialize Blastxcss selector."""
        super().__init__(database, constraints)
        logger.info("BlastxcssSelector initialized (high-energy mode)")

    def _estimate_progress(self, current_duration: float, target_duration: float) -> float:
        """
        Calculate progress through mix (0.0-1.0).

        Args:
            current_duration: Elapsed duration in seconds
            target_duration: Total target duration in seconds

        Returns:
            Progress ratio (0.0 = start, 0.5 = middle, 1.0 = end)
        """
        if target_duration <= 0:
            return 0.0
        return min(1.0, current_duration / target_duration)

    def _target_energy_for_position(self, progress: float) -> float:
        """
        Calculate ideal energy for current mix position.

        Energy curve: 0.3 (intro) → 0.8 (peak at 0.5) → 0.4 (outro)

        Args:
            progress: Progress through mix (0.0-1.0)

        Returns:
            Target energy level (0.0-1.0)
        """
        if progress < 0.3:
            # Intro phase: build from 0.3
            return 0.3 + (progress / 0.3) * 0.2
        elif progress < 0.5:
            # Build phase: 0.5 → 0.8
            mid = (progress - 0.3) / 0.2
            return 0.5 + mid * 0.3
        elif progress < 0.7:
            # Peak phase: sustain at 0.8
            return 0.8
        else:
            # Outro phase: 0.8 → 0.4
            outro = (progress - 0.7) / 0.3
            return 0.8 - outro * 0.4

    def choose_next(
        self,
        current_track: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        progress: float = 0.0,
    ) -> Optional[tuple]:
        """
        Choose next track with energy curve preference.

        Overrides Merlin's choose_next to add energy curve awareness.

        Args:
            current_track: Current track metadata
            candidates: List of candidate tracks
            progress: Progress through mix (0.0-1.0)

        Returns:
            Tuple (track_id, hints) or None
        """
        from .energy import estimate_track_energy, compute_energy_distance

        if not candidates:
            logger.debug("No candidates available")
            return None

        # Get target energy for this position
        target_energy = self._target_energy_for_position(progress)
        logger.debug(f"Progress: {progress:.2f}, Target energy: {target_energy:.2f}")

        # Filter by constraints (harmonic, BPM, repeat decay)
        valid_candidates = []

        for candidate in candidates:
            track_id = candidate.get("id")
            if track_id in self.used_in_set:
                continue

            if self._is_recently_used(track_id, self.constraints.max_repeat_decay):
                logger.debug(f"Track {track_id} recently used; skipping")
                continue

            # Check BPM compatibility
            if not self._bpm_compatible(
                current_track.get("bpm"),
                candidate.get("bpm"),
                self.constraints.bpm_tolerance,
            ):
                logger.debug(f"Track {track_id} BPM incompatible")
                continue

            # Check harmonic compatibility
            if not self._camelot_compatible(current_track.get("key"), candidate.get("key")):
                logger.debug(f"Track {track_id} key incompatible")
                continue

            valid_candidates.append(candidate)

        if not valid_candidates:
            logger.debug("No valid candidates after filtering")
            return None

        # Score candidates by energy proximity to target
        scored = []
        for candidate in valid_candidates:
            track_id = candidate.get("id")
            candidate_energy = estimate_track_energy(candidate)
            energy_distance = compute_energy_distance(target_energy, candidate_energy)

            # Prefer candidates close to target energy
            # (lower distance = better)
            scored.append((track_id, candidate_energy, energy_distance, candidate))

        # Sort by energy distance (ascending)
        scored.sort(key=lambda x: x[2])

        # Pick best match
        chosen_id, chosen_energy, distance, chosen = scored[0]
        self.used_in_set.add(chosen_id)

        hints = {
            "bpm": chosen.get("bpm"),
            "key": chosen.get("key"),
            "energy": chosen_energy,
            "target_energy": target_energy,
            "energy_distance": distance,
            "valid_count": len(valid_candidates),
        }

        logger.debug(
            f"Chose {chosen_id}: energy={chosen_energy:.2f}, "
            f"target={target_energy:.2f}, distance={distance:.2f}"
        )

        return (chosen_id, hints)

    def build_playlist(
        self,
        library: List[Dict[str, Any]],
        seed_track_id: str,
        target_duration_minutes: int,
        max_tracks: int = 90,
    ) -> Optional[List[str]]:
        """
        Build high-energy playlist with energy curve.

        Args:
            library: List of track metadata
            seed_track_id: Starting track ID
            target_duration_minutes: Target mix duration
            max_tracks: Maximum number of tracks

        Returns:
            List of track IDs, or None if generation failed
        """
        library_dict = {t.get("id"): t for t in library}

        if seed_track_id not in library_dict:
            logger.error(f"Seed track {seed_track_id} not found")
            return None

        seed_track = library_dict[seed_track_id]
        playlist = [seed_track_id]
        total_duration = seed_track.get("duration_seconds", 0)
        target_duration_seconds = target_duration_minutes * 60

        self.used_in_set.add(seed_track_id)

        logger.info(
            f"Building high-energy playlist from {seed_track_id} "
            f"(target: {target_duration_minutes}min)"
        )

        current_track = seed_track
        iteration = 1

        # Greedy loop with energy curve awareness
        while total_duration < target_duration_seconds and len(playlist) < max_tracks:
            # Calculate progress
            progress = total_duration / target_duration_seconds if target_duration_seconds > 0 else 0.0

            # Get remaining candidates
            candidates = [
                t for t in library
                if t.get("id") not in self.used_in_set
                and t.get("duration_seconds", 0) >= self.constraints.min_duration
            ]

            if not candidates:
                logger.warning("No more valid candidates")
                break

            # Choose next with energy curve consideration
            result = self.choose_next(current_track, candidates, progress=progress)
            if result is None:
                logger.warning("No compatible next track found")
                break

            next_track_id, hints = result
            next_track = library_dict[next_track_id]

            playlist.append(next_track_id)
            total_duration += next_track.get("duration_seconds", 0)

            logger.debug(
                f"Iteration {iteration}: added {next_track_id} "
                f"(energy: {hints.get('energy', 0):.2f}, "
                f"total: {total_duration}s)"
            )

            current_track = next_track
            iteration += 1

        logger.info(
            f"✅ High-energy playlist built: {len(playlist)} tracks, "
            f"{total_duration}s ({total_duration/60:.1f}min)"
        )

        return playlist


def select_playlist(
    library: Dict[str, Any],
    seed_track_id: str,
    target_duration_minutes: int,
    constraints: SelectionConstraints,
    database=None,
    selector_mode: str = "merlin",
) -> Optional[List[str]]:
    """
    Generate a playlist using greedy graph traversal.

    Args:
        library: List of track metadata dicts (from database)
        seed_track_id: Starting track ID
        target_duration_minutes: Target mix duration in minutes
        constraints: SelectionConstraints object
        database: Database connection (for repeat decay checks)
        selector_mode: "merlin" (balanced) or "blastxcss" (high-energy)

    Returns:
        List of track IDs in playback order, or None if generation failed
    """
    if selector_mode == "blastxcss":
        selector = BlastxcssSelector(database, constraints)
    else:
        selector = MerlinGreedySelector(database, constraints)

    return selector.build_playlist(library, seed_track_id, target_duration_minutes)
