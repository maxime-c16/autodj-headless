"""
Playlist and Transition Plan Generation (ArchwizardPhonemius).

Per SPEC.md § 4.3 (Transition Plan):
- Output: playlist.m3u and transitions.json
- Transitions contain: mix_in, hold_duration, target_bpm, exit_cue, effect, etc.
"""

import json
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from .selector import MerlinGreedySelector, SelectionConstraints

logger = logging.getLogger(__name__)


class TransitionPlan:
    """Represents a single transition between two tracks."""

    def __init__(
        self,
        track_index: int,
        track_id: int,
        entry_cue: str = "cue_in",
        hold_duration_bars: int = 16,
        target_bpm: float = None,
        exit_cue: str = "cue_out",
        mix_out_seconds: float = 4.0,
        effect: str = "smart_crossfade",
        next_track_id: Optional[int] = None,
    ):
        """
        Args:
            track_index: Position in playlist (0-based)
            track_id: Database ID of track
            entry_cue: Cue point to start from ("cue_in", "loop_start", etc.)
            hold_duration_bars: Bars to hold before transition
            target_bpm: Rendered BPM for this track
            exit_cue: Cue point to transition from
            mix_out_seconds: Crossfade duration
            effect: Transition effect ("smart_crossfade", "filter_swap", etc.)
            next_track_id: ID of following track
        """
        self.track_index = track_index
        self.track_id = track_id
        self.entry_cue = entry_cue
        self.hold_duration_bars = hold_duration_bars
        self.target_bpm = target_bpm
        self.exit_cue = exit_cue
        self.mix_out_seconds = mix_out_seconds
        self.effect = effect
        self.next_track_id = next_track_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "track_index": self.track_index,
            "track_id": self.track_id,
            "entry_cue": self.entry_cue,
            "hold_duration_bars": self.hold_duration_bars,
            "target_bpm": self.target_bpm,
            "exit_cue": self.exit_cue,
            "mix_out_seconds": self.mix_out_seconds,
            "effect": self.effect,
            "next_track_id": self.next_track_id,
        }


class ArchwizardPhonemius:
    """
    Playlist and transition plan generator (Phonemius).

    Orchestrates track selection, transition planning, and output generation.
    """

    def __init__(self, database, config: dict):
        """
        Initialize Phonemius with database and configuration.

        Args:
            database: Database connection for track metadata
            config: Configuration dict
        """
        self.db = database
        self.config = config
        self.constraints = SelectionConstraints(config.get("constraints", {}))
        logger.info("ArchwizardPhonemius initialized")

    def _select_seed_track(self, library: List[Dict[str, Any]], seed_track_id: Optional[str] = None) -> Optional[str]:
        """
        Select seed track for playlist generation.

        Args:
            library: List of track metadata
            seed_track_id: Explicit seed ID, or None to pick randomly

        Returns:
            Track ID to start with, or None if library is empty
        """
        if not library:
            logger.error("Empty library; cannot select seed track")
            return None

        if seed_track_id:
            # Explicit seed
            if any(t.get("id") == seed_track_id for t in library):
                logger.info(f"Using explicit seed track: {seed_track_id}")
                return seed_track_id
            else:
                logger.warning(f"Seed track {seed_track_id} not found; picking random")

        # Pick random seed with sufficient minimum duration
        min_duration = self.constraints.min_duration
        candidates = [t for t in library if t.get("duration_seconds", 0) >= min_duration]

        if not candidates:
            logger.error(f"No tracks with duration >= {min_duration}s")
            return None

        seed = random.choice(candidates)
        seed_id = seed.get("id")
        logger.info(f"Selected random seed track: {seed_id} ({seed.get('bpm')} BPM, {seed.get('key')})")
        return seed_id

    def _plan_transitions(
        self,
        track_ids: List[str],
        library_dict: Dict[str, Dict[str, Any]],
    ) -> List[TransitionPlan]:
        """
        Plan transitions between consecutive tracks.

        Args:
            track_ids: Ordered list of track IDs
            library_dict: Track metadata lookup dict

        Returns:
            List of TransitionPlan objects
        """
        transitions = []

        for idx, track_id in enumerate(track_ids):
            track = library_dict.get(track_id, {})
            next_track_id = track_ids[idx + 1] if idx + 1 < len(track_ids) else None

            # Determine transition parameters
            hold_duration_bars = 16  # 16 bars at current BPM
            mix_out_seconds = self.config.get("render", {}).get("crossfade_duration_seconds", 4.0)
            effect = self._select_transition_effect(track.get("key"), track_ids[idx + 1] if next_track_id else None, library_dict)

            plan = TransitionPlan(
                track_index=idx,
                track_id=track_id,
                entry_cue="cue_in",
                hold_duration_bars=hold_duration_bars,
                target_bpm=track.get("bpm"),
                exit_cue="cue_out",
                mix_out_seconds=mix_out_seconds,
                effect=effect,
                next_track_id=next_track_id,
            )
            transitions.append(plan)

        logger.info(f"Planned {len(transitions)} transitions")
        return transitions

    def _select_transition_effect(self, current_key: Optional[str], next_track_id: Optional[str], library_dict: Dict[str, Dict[str, Any]]) -> str:
        """
        Select appropriate transition effect based on harmonic context.

        Args:
            current_key: Current track key
            next_track_id: ID of next track (or None if final)
            library_dict: Track metadata lookup

        Returns:
            Effect name ("smart_crossfade", "filter_swap", etc.)
        """
        if not next_track_id:
            return "smart_crossfade"  # Default for final track

        next_track = library_dict.get(next_track_id, {})
        next_key = next_track.get("key")

        # If keys match exactly, use simple crossfade
        if current_key == next_key:
            return "smart_crossfade"

        # Default to smart crossfade (handles key/BPM matching)
        return "smart_crossfade"

    def build_playlist(
        self,
        library: List[Dict[str, Any]],
        target_duration_minutes: int,
        seed_track_id: Optional[str] = None,
        playlist_id: Optional[str] = None,
    ) -> Optional[Tuple[List[str], List[TransitionPlan]]]:
        """
        Build complete playlist with transition plan.

        Args:
            library: List of track metadata dicts
            target_duration_minutes: Target mix duration
            seed_track_id: Explicit seed track ID, or None for random
            playlist_id: Unique identifier for playlist (auto-generated if None)

        Returns:
            Tuple of (track_ids, transitions) or None if generation failed
        """
        # Generate playlist ID if not provided
        if playlist_id is None:
            playlist_id = f"autodj-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        logger.info(f"Building playlist {playlist_id} (target: {target_duration_minutes}min)")

        # Select seed track
        seed_id = self._select_seed_track(library, seed_track_id)
        if not seed_id:
            logger.error("Failed to select seed track")
            return None

        # Use Merlin selector to build playlist
        selector = MerlinGreedySelector(self.db, self.constraints)
        track_ids = selector.build_playlist(library, seed_id, target_duration_minutes)

        if not track_ids or len(track_ids) < 2:
            logger.error("Selector returned insufficient tracks")
            return None

        # Plan transitions
        library_dict = {t.get("id"): t for t in library}
        transitions = self._plan_transitions(track_ids, library_dict)

        logger.info(f"✅ Playlist built: {len(track_ids)} tracks, {len(transitions)} transitions")
        return (track_ids, transitions)


def generate(
    track_ids: Optional[List[str]] = None,
    library: Optional[List[Dict[str, Any]]] = None,
    config: Optional[dict] = None,
    output_dir: str = "data/playlists",
    target_duration_minutes: Optional[int] = None,
    seed_track_id: Optional[str] = None,
    database=None,
) -> Optional[tuple]:
    """
    Generate playlist.m3u and transitions.json (full end-to-end generation).

    Supports two modes:
    1. Direct: pass explicit track_ids + library
    2. Orchestrated: pass config + database + target_duration (uses Phonemius)

    Args:
        track_ids: Ordered list of track IDs (optional, used for direct mode)
        library: Track metadata list (required for m3u generation)
        config: Configuration dict
        output_dir: Directory to write outputs
        target_duration_minutes: Target mix duration (triggers Phonemius mode)
        seed_track_id: Seed track for Phonemius (optional)
        database: Database connection (required for Phonemius)

    Returns:
        Tuple of (playlist_path, transitions_path) or None if failed
    """
    if config is None:
        logger.error("Configuration required")
        return None

    # Mode 1: Orchestrated generation (Phonemius)
    if target_duration_minutes is not None and database is not None and library is not None:
        logger.info("Using orchestrated playlist generation (Phonemius)")
        phonemius = ArchwizardPhonemius(database, config)
        result = phonemius.build_playlist(library, target_duration_minutes, seed_track_id=seed_track_id)
        if result is None:
            return None
        track_ids, transitions = result

    # Mode 2: Direct mode (explicit track IDs)
    elif track_ids is None or library is None:
        logger.error("Either (target_duration_minutes + database) or (track_ids + library) required")
        return None
    else:
        # Generate basic transitions for direct mode
        library_dict = {t.get("id"): t for t in library}
        transitions = [
            TransitionPlan(
                track_index=idx,
                track_id=tid,
                next_track_id=track_ids[idx + 1] if idx + 1 < len(track_ids) else None,
            )
            for idx, tid in enumerate(track_ids)
        ]

    # Common: Write output files
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate M3U playlist
    library_dict = {t.get("id"): t for t in library}
    track_paths = [library_dict.get(tid, {}).get("file_path") for tid in track_ids]
    track_paths = [p for p in track_paths if p]  # Filter out None values

    playlist_filename = f"playlist-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.m3u"
    playlist_path = output_path / playlist_filename

    if not write_m3u(track_paths, playlist_path, library_dict=library_dict):
        logger.error("Failed to write M3U")
        return None

    # Generate transitions JSON
    transitions_filename = f"transitions-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    transitions_path = output_path / transitions_filename

    total_duration = sum(library_dict.get(tid, {}).get("duration_seconds", 0) for tid in track_ids)

    if not write_transitions(transitions, "autodj-playlist", int(total_duration), transitions_path):
        logger.error("Failed to write transitions")
        return None

    logger.info(f"✅ Generated playlist and transitions")
    return (str(playlist_path), str(transitions_path))


def write_m3u(
    track_paths: List[str],
    output_path: Path,
    library_dict: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
    """
    Write M3U playlist file.

    Per SPEC.md § 4.2: All paths must be absolute.

    Args:
        track_paths: List of absolute file paths
        output_path: Output M3U file path
        library_dict: Optional track metadata dict (for accurate durations)

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_path, "w") as f:
            f.write("#EXTM3U\n")
            for path in track_paths:
                # Get duration from metadata if available
                if library_dict:
                    # Try to find track by path
                    track_meta = next((t for t in library_dict.values() if t.get("file_path") == path), None)
                    duration = int(track_meta.get("duration_seconds", 180)) if track_meta else 180
                else:
                    duration = 180  # Default placeholder

                filename = Path(path).stem
                f.write(f"#EXT-INF:{duration},{filename}\n")
                f.write(f"{path}\n")
        logger.info(f"Wrote playlist: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write M3U: {e}")
        return False


def write_transitions(
    transitions: List[TransitionPlan],
    playlist_id: str,
    mix_duration_seconds: int,
    output_path: Path,
) -> bool:
    """
    Write transition plan JSON.

    Per SPEC.md § 4.3: All timings must be sample-accurate.

    Args:
        transitions: List of TransitionPlan objects
        playlist_id: Unique identifier for this playlist
        mix_duration_seconds: Total mix duration
        output_path: Output JSON file path

    Returns:
        True if successful, False otherwise
    """
    try:
        plan = {
            "playlist_id": playlist_id,
            "mix_duration_seconds": mix_duration_seconds,
            "generated_at": datetime.utcnow().isoformat(),
            "transitions": [t.to_dict() for t in transitions],
        }
        with open(output_path, "w") as f:
            json.dump(plan, f, indent=2)
        logger.info(f"Wrote transitions: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write transitions: {e}")
        return False
