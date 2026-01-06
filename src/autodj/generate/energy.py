"""
Energy Continuity Analysis: Ensure smooth energy transitions.

Per SPEC.md § 5.2:
- Look ahead at energy_window_size tracks
- Compute energy variance in window
- Prefer low-variance transitions (smooth)
- Boundary condition: Energy at cue_in must match previous cue_out
"""

import logging
import math
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def estimate_track_energy(track: Dict[str, Any]) -> float:
    """
    Estimate energy level of a track (0.0-1.0).

    Energy is estimated as:
    1. Primary: Loudness at cue_in (entry energy)
    2. Fallback: Median of cue_in + cue_out energies
    3. Final fallback: Neutral 0.5 (no data)

    Args:
        track: Track metadata with optional energy fields

    Returns:
        Energy estimate (0.0=quiet, 1.0=loud), normalized to [0.0, 1.0]
    """
    # Check if track has explicit energy metadata
    if "energy" in track and track["energy"] is not None:
        # Already computed, just normalize
        energy = float(track["energy"])
        return max(0.0, min(1.0, energy))

    # Try to estimate from cue energies if available
    cue_in_energy = track.get("cue_in_energy")
    cue_out_energy = track.get("cue_out_energy")

    if cue_in_energy is not None:
        # Entry energy is the primary indicator
        energy = float(cue_in_energy)
        return max(0.0, min(1.0, energy))

    if cue_out_energy is not None:
        # Exit energy as fallback
        energy = float(cue_out_energy)
        return max(0.0, min(1.0, energy))

    # Estimate from loudness if available (in dB)
    loudness_db = track.get("loudness_db")
    if loudness_db is not None:
        # Normalize dB to 0.0-1.0 range
        # Assume range: -40dB (quiet) to 0dB (loud)
        normalized = (float(loudness_db) + 40.0) / 40.0
        return max(0.0, min(1.0, normalized))

    # Estimate from BPM as very rough proxy (higher BPM → potentially higher energy)
    bpm = track.get("bpm")
    if bpm is not None:
        # Very rough: assume 80-180 BPM range
        normalized = (float(bpm) - 80.0) / 100.0
        return max(0.0, min(1.0, normalized))

    # No data available; assume neutral energy
    logger.debug(f"No energy data for track {track.get('id')}; using neutral 0.5")
    return 0.5


def compute_energy_distance(energy1: float, energy2: float) -> float:
    """
    Compute energy distance between two tracks (0.0-1.0).

    Args:
        energy1: Energy of first track (0.0-1.0)
        energy2: Energy of second track (0.0-1.0)

    Returns:
        Distance (0.0=same, 1.0=opposite)
    """
    return abs(energy1 - energy2)


def compute_energy_score(
    current_track: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    energy_window_size: int = 3,
) -> Dict[str, float]:
    """
    Score candidate tracks by energy continuity.

    Scoring criteria:
    1. Energy distance: |current_exit - candidate_entry|
    2. Variance lookahead: average energy in next N candidates
    3. Prefer smooth, gradual energy transitions

    Args:
        current_track: Current track metadata
        candidates: List of candidate tracks to score
        energy_window_size: Number of tracks to lookahead (default: 3)

    Returns:
        Dict mapping track_id -> energy_score (lower = better continuity)
        Returns empty dict if no candidates
    """
    if not candidates:
        return {}

    # Get current track's exit energy (use cue_out if available, else overall energy)
    current_energy = estimate_track_energy(current_track)
    logger.debug(f"Current track energy: {current_energy:.2f}")

    scores = {}

    for idx, candidate in enumerate(candidates):
        candidate_id = candidate.get("id")
        if not candidate_id:
            continue

        # Estimate candidate's entry energy
        candidate_energy = estimate_track_energy(candidate)

        # Primary score: distance from current energy
        distance_score = compute_energy_distance(current_energy, candidate_energy)

        # Secondary score: lookahead variance
        # Look at next N candidates to prefer smooth paths
        lookahead_energies = []
        for j in range(idx + 1, min(idx + energy_window_size, len(candidates))):
            lookahead_energies.append(estimate_track_energy(candidates[j]))

        if lookahead_energies:
            # Compute variance in lookahead window
            mean_lookahead = sum(lookahead_energies) / len(lookahead_energies)
            variance = sum((e - mean_lookahead) ** 2 for e in lookahead_energies) / len(
                lookahead_energies
            )
            variance_score = math.sqrt(variance)  # Normalize with sqrt
        else:
            variance_score = 0.0

        # Combine scores: prefer energy distance over variance
        # Weight: 70% distance, 30% variance
        combined_score = 0.7 * distance_score + 0.3 * variance_score

        scores[candidate_id] = combined_score

        logger.debug(
            f"Candidate {candidate_id}: energy={candidate_energy:.2f}, "
            f"distance={distance_score:.2f}, variance={variance_score:.2f}, "
            f"score={combined_score:.2f}"
        )

    return scores


def rank_candidates_by_energy(
    current_track: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    energy_window_size: int = 3,
) -> List[tuple]:
    """
    Rank candidate tracks by energy continuity (best first).

    Args:
        current_track: Current track metadata
        candidates: List of candidate tracks
        energy_window_size: Lookahead window size

    Returns:
        List of (track_id, energy_score) tuples, sorted by score (ascending)
    """
    scores = compute_energy_score(current_track, candidates, energy_window_size)

    # Sort by score (lower is better)
    ranked = sorted(scores.items(), key=lambda x: x[1])

    return ranked
