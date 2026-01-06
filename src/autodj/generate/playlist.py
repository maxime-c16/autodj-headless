"""
Playlist and Transition Plan Generation.

Per SPEC.md § 4.3 (Transition Plan):
- Output: playlist.m3u and transitions.json
- Transitions contain: mix_in, hold_duration, target_bpm, exit_cue, effect, etc.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

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


def generate(
    track_ids: List[int],
    library: Dict[str, Any],
    config: dict,
    output_dir: str = "data/playlists",
) -> Optional[tuple]:
    """
    Generate playlist.m3u and transitions.json.

    Args:
        track_ids: Ordered list of track IDs from selector
        library: Track metadata from database
        config: Configuration dict
        output_dir: Directory to write outputs

    Returns:
        Tuple of (playlist_path, transitions_path) or None if failed
    """
    # TODO: Implement playlist generation
    # 1. Create M3U file with absolute paths
    # 2. Create transitions.json with mix instructions
    # 3. Handle BPM adjustment (time-stretching)
    # 4. Validate total duration matches config
    # 5. Write to output_dir
    # 6. Return (playlist_path, transitions_path)

    logger.warning("Playlist generation not yet implemented")
    return None


def write_m3u(
    track_paths: List[str],
    output_path: Path,
) -> bool:
    """
    Write M3U playlist file.

    Per SPEC.md § 4.2: All paths must be absolute.

    Args:
        track_paths: List of absolute file paths
        output_path: Output M3U file path

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_path, "w") as f:
            f.write("#EXTM3U\n")
            for path in track_paths:
                # Get duration from metadata (TODO: populate from library)
                duration = 180  # Placeholder
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
