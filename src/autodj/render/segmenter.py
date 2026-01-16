"""
Segment-based rendering for large mixes.

Splits long transitions into manageable segments to reduce peak memory usage.
Per SPEC.md § 5.3: Peak RAM ~200 MiB per segment instead of 512+ MiB for full mix.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SegmentPlan:
    """Render plan for a single segment."""

    segment_index: int                    # 0, 1, 2, ...
    track_start_idx: int                  # First track index in original playlist
    track_end_idx: int                    # Last track index (exclusive)
    transitions: List[dict] = field(default_factory=list)  # Subset of transitions
    has_prev_segment: bool = False        # Is there a previous segment?
    has_next_segment: bool = False        # Is there a next segment?
    overlap_with_prev: int = 0            # Number of overlapping tracks with previous
    overlap_with_next: int = 0            # Number of overlapping tracks with next
    estimated_duration_sec: float = 0.0   # Calculated from transitions
    estimated_memory_mb: int = 0          # Peak RAM estimate

    def __post_init__(self):
        """Calculate segment duration and memory estimate."""
        # Calculate duration from transitions
        total_duration = 0.0
        for trans in self.transitions:
            hold_duration_bars = trans.get("hold_duration_bars", 16)
            target_bpm = trans.get("target_bpm", 120)
            if hold_duration_bars and target_bpm:
                # bars_to_seconds = (bars / 4) * (60 / bpm)
                bar_duration_sec = (hold_duration_bars / 4) * (60 / target_bpm)
                total_duration += bar_duration_sec

        self.estimated_duration_sec = total_duration

        # Estimate memory: ~50 MB per track + 50 MB overhead
        self.estimated_memory_mb = (len(self.transitions) * 50) + 50


class RenderSegmenter:
    """Split transitions into renderable segments."""

    def __init__(self, max_tracks_per_segment: int = 5):
        """
        Initialize segmenter.

        Args:
            max_tracks_per_segment: Target tracks per segment (default 5)
        """
        self.max_tracks_per_segment = max_tracks_per_segment
        logger.debug(f"RenderSegmenter initialized: {max_tracks_per_segment} tracks/segment")

    def split_transitions(
        self,
        transitions: List[dict],
        max_tracks_per_segment: Optional[int] = None,
    ) -> List[SegmentPlan]:
        """
        Split transitions into segments WITHOUT overlap on render.

        Strategy: Each segment is independent (no overlapping tracks).
            Segment 1: [Track 0-4]    (5 tracks)
            Segment 2: [Track 5-9]    (5 tracks, fresh start)
            Segment 3: [Track 10-14]  (5 tracks, fresh start)

        Segments are concatenated directly without crossfade blending
        (blending already happened within Liquidsoap DSP).

        Args:
            transitions: List of transition dicts from transitions.json
            max_tracks_per_segment: Override max tracks per segment

        Returns:
            List of SegmentPlan with boundaries and overlap info
        """
        if max_tracks_per_segment is None:
            max_tracks_per_segment = self.max_tracks_per_segment

        segments = []

        if not transitions:
            logger.warning("No transitions to segment")
            return segments

        logger.info(
            f"Segmenting {len(transitions)} transitions "
            f"(max {max_tracks_per_segment} per segment)"
        )

        i = 0
        while i < len(transitions):
            # Take next N tracks (NO OVERLAP)
            end_idx = min(i + max_tracks_per_segment, len(transitions))
            segment_transitions = transitions[i:end_idx]

            # Determine if this is first/last segment
            has_prev = i > 0
            has_next = end_idx < len(transitions)

            # Create segment (NO OVERLAP between segments on render)
            segment = SegmentPlan(
                segment_index=len(segments),
                track_start_idx=i,
                track_end_idx=end_idx,
                transitions=segment_transitions,
                has_prev_segment=has_prev,
                has_next_segment=has_next,
                overlap_with_prev=0,  # NO OVERLAP
                overlap_with_next=0,  # NO OVERLAP
            )

            segments.append(segment)

            logger.debug(
                f"Segment {segment.segment_index}: "
                f"tracks [{segment.track_start_idx}:{segment.track_end_idx}] "
                f"({len(segment_transitions)} transitions, "
                f"~{segment.estimated_memory_mb} MB RAM, "
                f"{segment.estimated_duration_sec:.1f} sec)"
            )

            # Move to next segment (NO OVERLAP)
            i = end_idx

        logger.info(f"Split into {len(segments)} segments")

        # Log summary
        total_duration = sum(s.estimated_duration_sec for s in segments)
        total_memory = max(s.estimated_memory_mb for s in segments) if segments else 0

        logger.info(
            f"Segmentation summary: "
            f"{len(segments)} segments, "
            f"~{total_memory} MB peak RAM per segment, "
            f"{total_duration:.1f} sec total duration"
        )

        return segments

    def estimate_segment_memory(self, segment: SegmentPlan) -> int:
        """
        Estimate peak RAM for segment (bytes).

        Args:
            segment: SegmentPlan to estimate

        Returns:
            Estimated memory in bytes
        """
        # Rough estimate: 50 MB per track + 50 MB overhead
        mb = segment.estimated_memory_mb
        return mb * 1024 * 1024

    @staticmethod
    def should_segment(
        transitions: List[dict],
        max_tracks_before_segment: int = 10,
    ) -> bool:
        """
        Determine if segmentation is needed.

        Args:
            transitions: List of transition dicts
            max_tracks_before_segment: Threshold for triggering segmentation

        Returns:
            True if segmentation should be used
        """
        num_tracks = len(transitions)
        should_seg = num_tracks > max_tracks_before_segment

        logger.info(
            f"Segmentation check: {num_tracks} tracks "
            f"{'> ' if should_seg else '≤ '}{max_tracks_before_segment} threshold"
        )

        return should_seg
