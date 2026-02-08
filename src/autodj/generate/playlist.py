"""
Playlist and Transition Plan Generation (ArchwizardPhonemius).

Per SPEC.md § 4.3 (Transition Plan):
- Output: playlist.m3u and transitions.json
- Transitions contain: mix_in, hold_duration, target_bpm, exit_cue, effect, etc.

Pro DJ mixing engine supports 5 transition types:
- bass_swap: Standard HPF out + LPF in (default)
- loop_hold: Hold outgoing loop, bring in incoming filtered
- drop_swap: Cut at breakdown, slam incoming at drop
- loop_roll: Progressive halving buildup (8->4->2->1 bars)
- eq_blend: Long gradual 3-band EQ swap (32 bars)
"""

import json
import logging
import random
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from .selector import MerlinGreedySelector, SelectionConstraints

logger = logging.getLogger(__name__)


class TransitionType(Enum):
    """Available transition types for pro DJ mixing."""
    BASS_SWAP = "bass_swap"
    LOOP_HOLD = "loop_hold"
    DROP_SWAP = "drop_swap"
    LOOP_ROLL = "loop_roll"
    EQ_BLEND = "eq_blend"


@dataclass
class TransitionSpec:
    """Specification for a single transition between two tracks."""
    type: TransitionType
    overlap_bars: int                                  # 8, 16, or 32 bars of overlap
    outgoing_end_seconds: float                        # Where outgoing track body stops
    incoming_start_seconds: float                      # Where incoming track body picks up after transition
    loop_start_seconds: Optional[float] = None         # Loop source region start
    loop_end_seconds: Optional[float] = None           # Loop source region end
    loop_bars: Optional[int] = None                    # Loop size in bars
    loop_repeats: Optional[int] = None                 # Number of loop repetitions
    roll_stages: Optional[list] = None                 # For loop_roll: [(bars, reps), ...]
    hpf_frequency: float = 200.0                       # Bass kill cutoff
    lpf_frequency: float = 2500.0                      # Incoming warmth cutoff


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
        file_path: Optional[str] = None,
        bpm: Optional[float] = None,
        cue_in_frames: Optional[int] = None,
        cue_out_frames: Optional[int] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        outro_start_seconds: Optional[float] = None,
        drop_position_seconds: Optional[float] = None,
        sections_json: Optional[str] = None,
        # Pro DJ v2 fields (all default for backward compat)
        transition_type: str = "bass_swap",
        overlap_bars: int = 8,
        incoming_start_seconds: Optional[float] = None,
        loop_start_seconds: Optional[float] = None,
        loop_end_seconds: Optional[float] = None,
        loop_bars: Optional[int] = None,
        loop_repeats: Optional[int] = None,
        roll_stages: Optional[str] = None,
        hpf_frequency: float = 200.0,
        lpf_frequency: float = 2500.0,
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
            file_path: Absolute path to audio file
            bpm: Native BPM from analysis
            cue_in_frames: Cue-in frame offset from analysis
            cue_out_frames: Cue-out frame offset from analysis
            title: Track title
            artist: Track artist
            outro_start_seconds: Where outgoing track's outro begins
            drop_position_seconds: Where incoming track's first drop is
            sections_json: Serialized sections for render reference
            transition_type: One of TransitionType values
            overlap_bars: Bars of overlap between tracks
            incoming_start_seconds: Where incoming body starts after transition
            loop_start_seconds: Loop source region start
            loop_end_seconds: Loop source region end
            loop_bars: Loop size in bars
            loop_repeats: Number of loop repetitions
            roll_stages: JSON array of (bars, reps) tuples
            hpf_frequency: Bass kill cutoff Hz
            lpf_frequency: Incoming warmth cutoff Hz
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
        self.file_path = file_path
        self.bpm = bpm
        self.cue_in_frames = cue_in_frames
        self.cue_out_frames = cue_out_frames
        self.title = title
        self.artist = artist
        self.outro_start_seconds = outro_start_seconds
        self.drop_position_seconds = drop_position_seconds
        self.sections_json = sections_json
        # Pro DJ v2 fields
        self.transition_type = transition_type
        self.overlap_bars = overlap_bars
        self.incoming_start_seconds = incoming_start_seconds
        self.loop_start_seconds = loop_start_seconds
        self.loop_end_seconds = loop_end_seconds
        self.loop_bars = loop_bars
        self.loop_repeats = loop_repeats
        self.roll_stages = roll_stages
        self.hpf_frequency = hpf_frequency
        self.lpf_frequency = lpf_frequency

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        d = {
            "track_index": self.track_index,
            "track_id": self.track_id,
            "entry_cue": self.entry_cue,
            "hold_duration_bars": self.hold_duration_bars,
            "target_bpm": self.target_bpm,
            "exit_cue": self.exit_cue,
            "mix_out_seconds": self.mix_out_seconds,
            "effect": self.effect,
            "next_track_id": self.next_track_id,
            "file_path": self.file_path,
            "bpm": self.bpm,
            "cue_in_frames": self.cue_in_frames,
            "cue_out_frames": self.cue_out_frames,
            "title": self.title,
            "artist": self.artist,
            "transition_type": self.transition_type,
            "overlap_bars": self.overlap_bars,
            "hpf_frequency": self.hpf_frequency,
            "lpf_frequency": self.lpf_frequency,
        }
        if self.outro_start_seconds is not None:
            d["outro_start_seconds"] = self.outro_start_seconds
        if self.drop_position_seconds is not None:
            d["drop_position_seconds"] = self.drop_position_seconds
        if self.sections_json is not None:
            d["sections_json"] = self.sections_json
        if self.incoming_start_seconds is not None:
            d["incoming_start_seconds"] = self.incoming_start_seconds
        if self.loop_start_seconds is not None:
            d["loop_start_seconds"] = self.loop_start_seconds
        if self.loop_end_seconds is not None:
            d["loop_end_seconds"] = self.loop_end_seconds
        if self.loop_bars is not None:
            d["loop_bars"] = self.loop_bars
        if self.loop_repeats is not None:
            d["loop_repeats"] = self.loop_repeats
        if self.roll_stages is not None:
            d["roll_stages"] = self.roll_stages
        return d


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

        Uses section data from track_analysis (if available) for
        musically intelligent mix points and transition type selection.

        Args:
            track_ids: Ordered list of track IDs
            library_dict: Track metadata lookup dict

        Returns:
            List of TransitionPlan objects
        """
        transitions = []
        fallback_xfade = self.config.get("render", {}).get("crossfade_duration_seconds", 4.0)

        # Load rich analysis data for all tracks (if available)
        analysis_cache = {}
        if self.db:
            for tid in track_ids:
                try:
                    analysis = self.db.get_track_analysis(tid)
                    if analysis:
                        analysis_cache[tid] = analysis
                except Exception:
                    pass

        prev_transition_type = None

        for idx, track_id in enumerate(track_ids):
            track = library_dict.get(track_id, {})
            next_track_id = track_ids[idx + 1] if idx + 1 < len(track_ids) else None

            # Native BPM from analysis
            native_bpm = track.get("bpm")

            # Target BPM: midpoint with next track for smooth progression
            if next_track_id and native_bpm:
                next_track = library_dict.get(next_track_id, {})
                next_bpm = next_track.get("bpm")
                if next_bpm:
                    target_bpm = (native_bpm + next_bpm) / 2.0
                else:
                    target_bpm = native_bpm
            else:
                target_bpm = native_bpm

            # Extract section-aware timing from rich analysis
            outro_start_seconds = None
            drop_position_seconds = None
            sections_json = None

            # Outgoing track: use outro start from analysis
            track_analysis = analysis_cache.get(track_id)
            if track_analysis:
                cue_points = track_analysis.get("cue_points")
                if cue_points:
                    mix_out_cue = next(
                        (c for c in cue_points if c.get("label") == "mix_out"), None
                    )
                    if mix_out_cue:
                        outro_start_seconds = mix_out_cue.get("position_seconds")
                sections = track_analysis.get("sections")
                if sections:
                    sections_json = json.dumps(sections)

            # Incoming track: use drop position from analysis
            next_analysis = None
            if next_track_id:
                next_analysis = analysis_cache.get(next_track_id)
                if next_analysis:
                    next_cue_points = next_analysis.get("cue_points")
                    if next_cue_points:
                        drop_cue = next(
                            (c for c in next_cue_points if c.get("label") == "drop_1"), None
                        )
                        if drop_cue:
                            drop_position_seconds = drop_cue.get("position_seconds")

            # Choose transition type using pro DJ decision engine
            transition_spec = self._choose_transition(
                outgoing_analysis=track_analysis,
                incoming_analysis=next_analysis,
                outgoing_track=track,
                incoming_track=library_dict.get(next_track_id, {}) if next_track_id else None,
                prev_type=prev_transition_type,
                bpm=native_bpm or 128.0,
            )

            # Compute bar-aligned mix_out from overlap_bars
            effective_bpm = native_bpm if native_bpm and native_bpm > 0 else 128.0
            mix_out_seconds = transition_spec.overlap_bars * 4 * 60.0 / effective_bpm

            prev_transition_type = transition_spec.type

            plan = TransitionPlan(
                track_index=idx,
                track_id=track_id,
                entry_cue="cue_in",
                hold_duration_bars=16,
                target_bpm=target_bpm,
                exit_cue="cue_out",
                mix_out_seconds=mix_out_seconds,
                effect="smart_crossfade",
                next_track_id=next_track_id,
                file_path=track.get("file_path"),
                bpm=native_bpm,
                cue_in_frames=track.get("cue_in_frames"),
                cue_out_frames=track.get("cue_out_frames"),
                title=track.get("title"),
                artist=track.get("artist"),
                outro_start_seconds=outro_start_seconds,
                drop_position_seconds=drop_position_seconds,
                sections_json=sections_json,
                transition_type=transition_spec.type.value,
                overlap_bars=transition_spec.overlap_bars,
                incoming_start_seconds=transition_spec.incoming_start_seconds,
                loop_start_seconds=transition_spec.loop_start_seconds,
                loop_end_seconds=transition_spec.loop_end_seconds,
                loop_bars=transition_spec.loop_bars,
                loop_repeats=transition_spec.loop_repeats,
                roll_stages=json.dumps(transition_spec.roll_stages) if transition_spec.roll_stages else None,
                hpf_frequency=transition_spec.hpf_frequency,
                lpf_frequency=transition_spec.lpf_frequency,
            )
            transitions.append(plan)

        logger.info(f"Planned {len(transitions)} transitions")
        return transitions

    def _choose_transition(
        self,
        outgoing_analysis: Optional[Dict],
        incoming_analysis: Optional[Dict],
        outgoing_track: Dict[str, Any],
        incoming_track: Optional[Dict[str, Any]],
        prev_type: Optional[TransitionType],
        bpm: float = 128.0,
    ) -> TransitionSpec:
        """
        Choose transition type and parameters based on track analysis data.

        Greedy scoring — same philosophy as MerlinGreedySelector.choose_next().
        Scores each transition type, picks highest, avoids repeating prev_type.

        Args:
            outgoing_analysis: Rich analysis dict for outgoing track (or None)
            incoming_analysis: Rich analysis dict for incoming track (or None)
            outgoing_track: Track metadata dict for outgoing track
            incoming_track: Track metadata dict for incoming track (or None)
            prev_type: Previous transition type (to avoid consecutive repeats)
            bpm: BPM for bar duration calculations

        Returns:
            TransitionSpec with chosen type and parameters
        """
        # No next track = final track, just use bass_swap default
        if incoming_track is None:
            return TransitionSpec(
                type=TransitionType.BASS_SWAP,
                overlap_bars=8,
                outgoing_end_seconds=0.0,
                incoming_start_seconds=0.0,
            )

        bar_duration = 4 * 60.0 / bpm  # seconds per bar

        # Extract loop regions from outgoing analysis
        out_loops = []
        out_sections = []
        if outgoing_analysis:
            out_loops = outgoing_analysis.get("loop_regions", [])
            out_sections = outgoing_analysis.get("sections", [])

        # Extract sections from incoming analysis
        in_sections = []
        in_cue_points = []
        if incoming_analysis:
            in_sections = incoming_analysis.get("sections", [])
            in_cue_points = incoming_analysis.get("cue_points", [])

        # Find best outgoing loop (prefer outro_loop, then drop_loop)
        best_loop = None
        for label_pref in ["outro_loop", "drop_loop", "intro_loop"]:
            for loop in out_loops:
                if loop.get("label") == label_pref and loop.get("stability", 0) > 0.6:
                    best_loop = loop
                    break
            if best_loop:
                break

        # Find incoming drop position
        incoming_drop_seconds = None
        for cue in in_cue_points:
            if cue.get("label") == "drop_1":
                incoming_drop_seconds = cue.get("position_seconds")
                break

        # Find incoming intro section
        has_incoming_intro = any(
            s.get("label") == "intro" for s in in_sections
        )

        # Find outgoing breakdown near end
        has_outgoing_breakdown = any(
            s.get("label") in ("breakdown", "outro") for s in out_sections
        )

        # Check energy levels
        out_energy = outgoing_track.get("energy", 0.5)
        in_energy = (incoming_track or {}).get("energy", 0.5)

        # Check key compatibility (for eq_blend preference)
        out_key = outgoing_track.get("key", "")
        in_key = (incoming_track or {}).get("key", "")
        keys_similar = _are_keys_compatible(out_key, in_key)

        # Score each transition type
        scores = {}

        # BASS_SWAP: default, always available (score 1.0)
        scores[TransitionType.BASS_SWAP] = 1.0

        # LOOP_HOLD: outgoing has stable loop + incoming has intro
        if best_loop and has_incoming_intro:
            scores[TransitionType.LOOP_HOLD] = 3.0
        elif best_loop:
            scores[TransitionType.LOOP_HOLD] = 2.0

        # DROP_SWAP: incoming has strong drop + outgoing has breakdown
        if incoming_drop_seconds and incoming_drop_seconds > 10.0 and has_outgoing_breakdown:
            scores[TransitionType.DROP_SWAP] = 3.5
        elif incoming_drop_seconds and incoming_drop_seconds > 10.0:
            scores[TransitionType.DROP_SWAP] = 2.0

        # LOOP_ROLL: outgoing has drop loop + high energy
        drop_loop = None
        for loop in out_loops:
            if loop.get("label") == "drop_loop" and loop.get("stability", 0) > 0.5:
                drop_loop = loop
                break
        if drop_loop and out_energy > 0.6:
            scores[TransitionType.LOOP_ROLL] = 2.5

        # EQ_BLEND: similar energy + compatible keys (only when we have real energy data)
        has_energy_data = "energy" in outgoing_track and "energy" in (incoming_track or {})
        if has_energy_data and keys_similar and abs(out_energy - in_energy) < 0.2:
            scores[TransitionType.EQ_BLEND] = 2.0

        # Variety rule: heavily penalize repeating previous type
        if prev_type and prev_type in scores:
            scores[prev_type] *= 0.1  # Near-zero penalty for consecutive repeat

        # Pick highest-scoring type
        best_type = max(scores, key=scores.get)

        # Build TransitionSpec based on chosen type
        return self._build_transition_spec(
            best_type, best_loop, drop_loop, incoming_drop_seconds,
            bpm, bar_duration, outgoing_analysis, incoming_analysis,
        )

    def _build_transition_spec(
        self,
        transition_type: TransitionType,
        best_loop: Optional[Dict],
        drop_loop: Optional[Dict],
        incoming_drop_seconds: Optional[float],
        bpm: float,
        bar_duration: float,
        outgoing_analysis: Optional[Dict],
        incoming_analysis: Optional[Dict],
    ) -> TransitionSpec:
        """Build a TransitionSpec for the chosen transition type."""

        if transition_type == TransitionType.LOOP_HOLD:
            loop = best_loop or {}
            loop_start = loop.get("start_seconds", 0.0)
            loop_end = loop.get("end_seconds", loop_start + 8 * bar_duration)
            loop_bars = loop.get("length_bars", 8)
            loop_repeats = 2  # 2x loop = 16 bars total
            overlap_bars = loop_bars * loop_repeats
            incoming_start = overlap_bars * bar_duration
            return TransitionSpec(
                type=TransitionType.LOOP_HOLD,
                overlap_bars=overlap_bars,
                outgoing_end_seconds=loop_start,
                incoming_start_seconds=incoming_start,
                loop_start_seconds=loop_start,
                loop_end_seconds=loop_end,
                loop_bars=loop_bars,
                loop_repeats=loop_repeats,
            )

        elif transition_type == TransitionType.DROP_SWAP:
            overlap_bars = 4
            overlap_sec = overlap_bars * bar_duration
            incoming_start = incoming_drop_seconds if incoming_drop_seconds else 0.0
            return TransitionSpec(
                type=TransitionType.DROP_SWAP,
                overlap_bars=overlap_bars,
                outgoing_end_seconds=0.0,  # Render will use cue_out minus overlap
                incoming_start_seconds=incoming_start + overlap_sec,
                hpf_frequency=200.0,
                lpf_frequency=20000.0,  # No LPF on incoming for full-power drop entry
            )

        elif transition_type == TransitionType.LOOP_ROLL:
            loop = drop_loop or {}
            loop_start = loop.get("start_seconds", 0.0)
            loop_end = loop.get("end_seconds", loop_start + 8 * bar_duration)
            # Progressive halving: 8->4->2->1 bars = 16 bars total
            roll_stages = [(8, 1), (4, 1), (2, 1), (1, 2)]
            overlap_bars = 16
            incoming_start = overlap_bars * bar_duration
            return TransitionSpec(
                type=TransitionType.LOOP_ROLL,
                overlap_bars=overlap_bars,
                outgoing_end_seconds=loop_start,
                incoming_start_seconds=incoming_start,
                loop_start_seconds=loop_start,
                loop_end_seconds=loop_end,
                loop_bars=8,
                roll_stages=roll_stages,
            )

        elif transition_type == TransitionType.EQ_BLEND:
            overlap_bars = 32
            incoming_start = overlap_bars * bar_duration
            return TransitionSpec(
                type=TransitionType.EQ_BLEND,
                overlap_bars=overlap_bars,
                outgoing_end_seconds=0.0,
                incoming_start_seconds=incoming_start,
                hpf_frequency=800.0,   # Mid-range HPF for gradual blend
                lpf_frequency=800.0,   # Mid-range LPF for warmth
            )

        else:
            # BASS_SWAP (default)
            overlap_bars = 8
            incoming_start = overlap_bars * bar_duration
            return TransitionSpec(
                type=TransitionType.BASS_SWAP,
                overlap_bars=overlap_bars,
                outgoing_end_seconds=0.0,
                incoming_start_seconds=incoming_start,
            )

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


def _are_keys_compatible(key_a: str, key_b: str) -> bool:
    """
    Check if two Camelot keys are compatible (same, adjacent, or parallel).

    Args:
        key_a: Camelot key (e.g., "8A", "5B") or empty/unknown
        key_b: Camelot key or empty/unknown

    Returns:
        True if harmonically compatible
    """
    if not key_a or not key_b:
        return True  # Unknown = wildcard

    # Parse Camelot notation
    try:
        num_a = int(key_a[:-1])
        mode_a = key_a[-1].upper()
        num_b = int(key_b[:-1])
        mode_b = key_b[-1].upper()
    except (ValueError, IndexError):
        return True  # Can't parse = wildcard

    # Same key
    if num_a == num_b and mode_a == mode_b:
        return True

    # Parallel mode (same number, different letter)
    if num_a == num_b:
        return True

    # Adjacent (±1 on wheel, same mode)
    if mode_a == mode_b:
        diff = abs(num_a - num_b)
        if diff == 1 or diff == 11:  # 12-position wheel wraps
            return True

    return False


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
        # Direct mode: use ArchwizardPhonemius for transition planning
        library_dict = {t.get("id"): t for t in library}
        phonemius = ArchwizardPhonemius(database, config)
        transitions = phonemius._plan_transitions(track_ids, library_dict)

    # Common: Write output files
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate M3U playlist
    library_dict = {t.get("id"): t for t in library}
    track_paths = [library_dict.get(tid, {}).get("file_path") for tid in track_ids]

    playlist_filename = f"playlist-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.m3u"
    playlist_path = output_path / playlist_filename

    if not write_m3u(track_paths, playlist_path, library_dict=library_dict):
        logger.error("Failed to write M3U")
        return None

    # Generate transitions JSON
    transitions_filename = f"transitions-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    transitions_path = output_path / transitions_filename

    total_duration = sum(library_dict.get(tid, {}).get("duration_seconds", 0) for tid in track_ids)

    # Fill file_path on transitions that don't already have one
    for idx, t in enumerate(transitions):
        if not t.file_path:
            try:
                t.file_path = track_paths[idx]
            except Exception:
                t.file_path = None

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
