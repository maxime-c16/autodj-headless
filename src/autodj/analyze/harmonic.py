"""
Phase 2: Harmonic Mixing Module (Reworked)
===========================================

Implements the Camelot Wheel harmonic analysis system for DJ mixing.
Calculates harmonic compatibility between tracks and suggests optimal
mixing sequences using wheel position distance.

Theory:
    The Camelot Wheel arranges the 24 musical keys (12 major + 12 minor)
    in a circle where adjacent positions are harmonically compatible
    (separated by a perfect fifth = 7 semitones).

    Compatibility is determined by **wheel position distance**, not
    semitone distance. Keys with adjacent Camelot numbers (e.g., 9B→10B)
    are harmonically compatible for DJ mixing.

    Compatible moves on the Camelot Wheel:
    - Same key (0 steps):           PERFECT   (e.g., 10B → 10B)
    - ±1 position, same mode:       EXCELLENT (e.g., 10B → 9B or 11B)
    - Same position, switch mode:   EXCELLENT (e.g., 10B → 10A)
    - ±2 positions, same mode:      GOOD      (e.g., 10B → 8B)
    - ±1 pos + mode switch:         GOOD      (e.g., 10B → 9A or 11A)
    - ±3 positions:                  ACCEPTABLE
    - ±4+ positions:                 POOR / INCOMPATIBLE

    Key Format: [1-12][A|B]
    - Numbers 1-12: Position on the circle of fifths
    - A = Major key, B = Minor key

    Reference: Mixed In Key (Camelot System)
    Reference: Mark Davis Harmonic Mixing Guide

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class CompatibilityLevel(IntEnum):
    """Harmonic compatibility scoring (higher = more compatible)."""
    PERFECT = 5       # Same key
    EXCELLENT = 4     # ±1 position on wheel, or relative major/minor
    GOOD = 3          # ±2 positions, or ±1 with mode switch
    ACCEPTABLE = 2    # ±3 positions (requires careful mixing)
    POOR = 1          # ±4-5 positions (not recommended)
    INCOMPATIBLE = 0  # ±6 positions (opposite side of wheel)


# All valid Camelot keys
CAMELOT_WHEEL_A_MAJOR = [f"{i}A" for i in range(1, 13)]
CAMELOT_WHEEL_B_MINOR = [f"{i}B" for i in range(1, 13)]
CAMELOT_WHEEL = CAMELOT_WHEEL_A_MAJOR + CAMELOT_WHEEL_B_MINOR

# Camelot number → actual musical key (for reference/display)
CAMELOT_TO_KEY_NAME = {
    "1A": "Ab Major",   "1B": "F minor",
    "2A": "Eb Major",   "2B": "C minor",
    "3A": "Bb Major",   "3B": "G minor",
    "4A": "F Major",    "4B": "D minor",
    "5A": "C Major",    "5B": "A minor",
    "6A": "G Major",    "6B": "E minor",
    "7A": "D Major",    "7B": "B minor",
    "8A": "A Major",    "8B": "F# minor",
    "9A": "E Major",    "9B": "C# minor",
    "10A": "B Major",   "10B": "G# minor",
    "11A": "F# Major",  "11B": "D# minor",
    "12A": "Db Major",  "12B": "Bb minor",
}

# Standard key name → Camelot (for conversion from key detection)
KEY_NAME_TO_CAMELOT = {v: k for k, v in CAMELOT_TO_KEY_NAME.items()}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Track:
    """Represents a DJ track with metadata."""
    index: int
    name: str
    camelot_key: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        """Validate Camelot key format."""
        if self.camelot_key not in CAMELOT_WHEEL:
            raise ValueError(
                f"Invalid Camelot key: {self.camelot_key}. "
                f"Must be 1A-12A or 1B-12B."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")


@dataclass
class Transition:
    """Represents a transition between two tracks."""
    from_key: str
    to_key: str
    compatibility_level: CompatibilityLevel
    compatibility_score: float
    technique: str
    semitone_distance: int


# ============================================================================
# CAMELOT WHEEL DISTANCE (Core Algorithm)
# ============================================================================

def _parse_key(key: str) -> Tuple[int, str]:
    """Parse Camelot key into (position, mode)."""
    mode = key[-1]
    position = int(key[:-1])
    return position, mode


def calculate_wheel_distance(key1: str, key2: str) -> int:
    """
    Calculate shortest distance on the Camelot wheel between two keys.

    Distance is the minimum number of steps around the 12-position circle
    (considering only the number, ignoring mode letter).

    Args:
        key1: Camelot key (e.g., "10B")
        key2: Camelot key (e.g., "9B")

    Returns:
        Wheel distance (0-6, where 6 is the maximum = opposite side)

    Examples:
        >>> calculate_wheel_distance("10B", "10B")
        0
        >>> calculate_wheel_distance("10B", "9B")
        1
        >>> calculate_wheel_distance("10B", "4B")
        6
    """
    pos1, _ = _parse_key(key1)
    pos2, _ = _parse_key(key2)

    raw_diff = abs(pos1 - pos2)
    return min(raw_diff, 12 - raw_diff)


def calculate_semitone_distance(key1: str, key2: str) -> int:
    """
    Calculate Camelot wheel distance between two keys.

    This function uses wheel position distance (not actual semitone distance)
    because the Camelot system is designed so that adjacent positions
    are harmonically compatible for DJ mixing.

    For cross-mode transitions (A↔B), we use the wheel distance
    of the numbers, which correctly captures the harmonic relationship.

    Args:
        key1: Camelot key (e.g., "10A")
        key2: Camelot key (e.g., "9B")

    Returns:
        Wheel distance (0-6)
    """
    if key1 not in CAMELOT_WHEEL or key2 not in CAMELOT_WHEEL:
        raise ValueError(f"Invalid key: {key1} or {key2}")

    pos1, mode1 = _parse_key(key1)
    pos2, mode2 = _parse_key(key2)

    # Same mode: pure wheel distance
    if mode1 == mode2:
        raw_diff = abs(pos1 - pos2)
        return min(raw_diff, 12 - raw_diff)

    # Cross-mode (A↔B): relative major/minor at same position is very close
    # Same position, different mode = relative major/minor = 1 step
    raw_diff = abs(pos1 - pos2)
    wheel_dist = min(raw_diff, 12 - raw_diff)

    # Mode switch adds 1 unit of distance (relative major/minor is close)
    return wheel_dist + 1 if wheel_dist > 0 else 1


def determine_compatibility(
    key1: str, key2: str,
) -> Tuple[CompatibilityLevel, float]:
    """
    Determine harmonic compatibility between two Camelot keys.

    Uses the Camelot wheel distance model:
    - Same key:                           PERFECT (5.0)
    - ±1 position same mode OR           EXCELLENT (4.0)
      same position different mode:
    - ±2 positions same mode OR           GOOD (3.0)
      ±1 position + mode switch:
    - ±3 positions:                       ACCEPTABLE (2.0)
    - ±4 positions:                       POOR (1.0)
    - ±5-6 positions:                     INCOMPATIBLE (0.0)

    Args:
        key1: First Camelot key
        key2: Second Camelot key

    Returns:
        Tuple of (CompatibilityLevel, score)
    """
    if key1 not in CAMELOT_WHEEL or key2 not in CAMELOT_WHEEL:
        raise ValueError(f"Invalid key: {key1} or {key2}")

    pos1, mode1 = _parse_key(key1)
    pos2, mode2 = _parse_key(key2)

    # Same key
    if pos1 == pos2 and mode1 == mode2:
        return CompatibilityLevel.PERFECT, 5.0

    # Wheel position distance
    raw_diff = abs(pos1 - pos2)
    wheel_dist = min(raw_diff, 12 - raw_diff)
    same_mode = (mode1 == mode2)

    # Relative major/minor: same position, different mode
    if wheel_dist == 0 and not same_mode:
        return CompatibilityLevel.EXCELLENT, 4.0

    # ±1 position, same mode
    if wheel_dist == 1 and same_mode:
        return CompatibilityLevel.EXCELLENT, 4.0

    # ±2 positions same mode, or ±1 + mode switch
    if wheel_dist == 2 and same_mode:
        return CompatibilityLevel.GOOD, 3.0
    if wheel_dist == 1 and not same_mode:
        return CompatibilityLevel.GOOD, 3.0

    # ±3 positions (any mode)
    if wheel_dist == 3 and same_mode:
        return CompatibilityLevel.ACCEPTABLE, 2.0
    if wheel_dist == 2 and not same_mode:
        return CompatibilityLevel.ACCEPTABLE, 2.0

    # ±4 or more
    if wheel_dist <= 4:
        return CompatibilityLevel.POOR, 1.0

    return CompatibilityLevel.INCOMPATIBLE, 0.0


def suggest_mixing_technique(compatibility: CompatibilityLevel) -> str:
    """
    Suggest DJ mixing technique based on harmonic compatibility.

    Args:
        compatibility: CompatibilityLevel enum value

    Returns:
        Technique name string
    """
    techniques = {
        CompatibilityLevel.PERFECT: "perfect_mix",
        CompatibilityLevel.EXCELLENT: "smooth_crossfade",
        CompatibilityLevel.GOOD: "careful_crossfade",
        CompatibilityLevel.ACCEPTABLE: "filter_sweep",
        CompatibilityLevel.POOR: "hard_cut",
        CompatibilityLevel.INCOMPATIBLE: "avoid_mixing",
    }
    return techniques.get(compatibility, "hard_cut")


# ============================================================================
# HARMONIC MIXER CLASS
# ============================================================================

class HarmonicMixer:
    """
    Main harmonic mixing analyzer.

    Manages tracks, calculates the compatibility matrix, finds optimal
    track sequences via greedy algorithm, and generates transition details.
    """

    def __init__(self) -> None:
        """Initialize empty mixer."""
        self.tracks: Dict[int, Track] = {}
        self._compatibility_matrix: Optional[List[List[float]]] = None
        logger.debug("HarmonicMixer initialized")

    def add_track(
        self,
        index: int,
        name: str,
        camelot_key: str,
        confidence: float = 1.0,
    ) -> None:
        """
        Add a track to the analysis.

        Args:
            index: Track index (0, 1, 2, ...)
            name: Track name/title
            camelot_key: Camelot key (e.g., "10A")
            confidence: Key detection confidence (0.0-1.0)

        Raises:
            ValueError: If key format is invalid
        """
        track = Track(
            index=index, name=name,
            camelot_key=camelot_key, confidence=confidence,
        )
        self.tracks[index] = track
        self._compatibility_matrix = None
        logger.debug(f"Added track {index}: {name} ({camelot_key})")

    def add_tracks_batch(self, tracks_data: List[Dict]) -> None:
        """
        Add multiple tracks at once.

        Args:
            tracks_data: List of dicts with keys: index, name, camelot_key, [confidence]
        """
        for data in tracks_data:
            self.add_track(**data)

    def calculate_compatibility_matrix(self) -> List[List[float]]:
        """
        Build NxN compatibility matrix for all tracks.

        Returns:
            NxN matrix where matrix[i][j] is compatibility score (0.0-5.0)
        """
        if self._compatibility_matrix is not None:
            return self._compatibility_matrix

        n = len(self.tracks)
        matrix = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix[i][j] = 5.0
                else:
                    key_i = self.tracks[i].camelot_key
                    key_j = self.tracks[j].camelot_key
                    _, score = determine_compatibility(key_i, key_j)
                    matrix[i][j] = score

        self._compatibility_matrix = matrix
        logger.debug(f"Calculated {n}x{n} compatibility matrix")
        return matrix

    def find_optimal_sequence(self) -> List[int]:
        """
        Find optimal track sequence using greedy algorithm.

        Strategy:
        1. Start with highest-confidence track
        2. At each step, select next track with highest compatibility
        3. No track used twice

        Returns:
            List of track indices in recommended mixing order
        """
        if not self.tracks:
            return []

        matrix = self.calculate_compatibility_matrix()
        n = len(self.tracks)

        start = max(
            self.tracks.keys(),
            key=lambda i: self.tracks[i].confidence,
        )

        sequence = [start]
        remaining = set(range(n)) - {start}

        while remaining:
            current = sequence[-1]
            best_next = max(remaining, key=lambda t: matrix[current][t])
            sequence.append(best_next)
            remaining.remove(best_next)

        logger.debug(f"Optimal sequence: {sequence}")
        return sequence

    def get_transitions(self, sequence: List[int]) -> List[Transition]:
        """
        Get transition details for a sequence of tracks.

        Args:
            sequence: List of track indices in mixing order

        Returns:
            List of Transition objects
        """
        transitions = []

        for i in range(len(sequence) - 1):
            from_idx = sequence[i]
            to_idx = sequence[i + 1]

            from_key = self.tracks[from_idx].camelot_key
            to_key = self.tracks[to_idx].camelot_key

            distance = calculate_semitone_distance(from_key, to_key)
            compat_level, score = determine_compatibility(from_key, to_key)
            technique = suggest_mixing_technique(compat_level)

            transition = Transition(
                from_key=from_key,
                to_key=to_key,
                compatibility_level=compat_level,
                compatibility_score=score,
                technique=technique,
                semitone_distance=distance,
            )
            transitions.append(transition)

        return transitions

    def get_recommendations(self) -> Dict:
        """
        Get comprehensive mixing recommendations.

        Returns:
            Dict with: tracks, compatibility_matrix, optimal_sequence, transitions
        """
        sequence = self.find_optimal_sequence()
        transitions = self.get_transitions(sequence)
        matrix = self.calculate_compatibility_matrix()

        return {
            "tracks": [asdict(self.tracks[i]) for i in range(len(self.tracks))],
            "compatibility_matrix": matrix,
            "optimal_sequence": sequence,
            "transitions": [asdict(t) for t in transitions],
        }

    def export_json(self, filepath: str) -> None:
        """
        Export analysis to JSON file.

        Args:
            filepath: Output JSON file path
        """
        recommendations = self.get_recommendations()

        output = {
            "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
            "track_count": len(self.tracks),
            "tracks": [asdict(self.tracks[i]) for i in range(len(self.tracks))],
            "compatibility_matrix": recommendations["compatibility_matrix"],
            "optimal_sequence": recommendations["optimal_sequence"],
            "transitions": [
                {
                    **t,
                    "compatibility_level": t["compatibility_level"].name,
                }
                for t in recommendations["transitions"]
            ],
        }

        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)

        logger.info(f"Exported analysis to {filepath}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def parse_camelot_key(key_str: str) -> Tuple[int, str]:
    """
    Parse Camelot key string into components.

    Args:
        key_str: Key string (e.g., "10A", "3B")

    Returns:
        Tuple of (position: int, mode: str)

    Raises:
        ValueError: If key format is invalid

    Examples:
        >>> parse_camelot_key("10A")
        (10, 'A')
        >>> parse_camelot_key("3B")
        (3, 'B')
    """
    if len(key_str) < 2:
        raise ValueError(f"Invalid key format: {key_str}")

    try:
        position = int(key_str[:-1])
        mode = key_str[-1]

        if not 1 <= position <= 12:
            raise ValueError(f"Position must be 1-12, got {position}")
        if mode not in ["A", "B"]:
            raise ValueError(f"Mode must be A or B, got {mode}")

        return position, mode
    except ValueError as e:
        raise ValueError(f"Invalid key format: {key_str}") from e


def key_name_to_camelot(key_name: str) -> Optional[str]:
    """
    Convert standard key name to Camelot notation.

    Args:
        key_name: Standard key name (e.g., "C Major", "A minor")

    Returns:
        Camelot key (e.g., "5A", "5B") or None if not found
    """
    return KEY_NAME_TO_CAMELOT.get(key_name)


def camelot_to_key_name(camelot_key: str) -> Optional[str]:
    """
    Convert Camelot notation to standard key name.

    Args:
        camelot_key: Camelot key (e.g., "5A")

    Returns:
        Standard key name (e.g., "C Major") or None if invalid
    """
    return CAMELOT_TO_KEY_NAME.get(camelot_key)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    mixer = HarmonicMixer()

    # Seed: "Deine Angst" by Klangkuenstler (10B = G# minor)
    mixer.add_tracks_batch([
        {"index": 0, "name": "Klangkuenstler - Deine Angst", "camelot_key": "10B"},
        {"index": 1, "name": "LOOCEE Ø - COLD HEART", "camelot_key": "9B"},
        {"index": 2, "name": "DΛVЯ - In Favor Of Noise", "camelot_key": "11B"},
        {"index": 3, "name": "Niki Istrefi - Red Armor", "camelot_key": "12B"},
    ])

    recommendations = mixer.get_recommendations()

    print("Optimal sequence:", recommendations["optimal_sequence"])
    print("Transitions:")
    for t in recommendations["transitions"]:
        print(
            f"  {t['from_key']} → {t['to_key']}: "
            f"{t['technique']} ({t['compatibility_score']}/5)"
        )
