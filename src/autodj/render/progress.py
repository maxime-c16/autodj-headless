"""
Wizard-style CLI progress tracker for DJ mix rendering.

Displays real-time progress with ASCII art, progress bars, track status,
and system metrics (memory, output size, elapsed time).
"""

import logging
import time
import os
import sys
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class WizardProgressTracker:
    """
    ASCII art progress tracker with real-time updates.

    Displays:
    - Current phase (e.g., "Rendering Segment 2/5")
    - Progress bar with percentage
    - Track-by-track status
    - Elapsed time and ETA
    - Memory usage
    - Output file size
    """

    def __init__(self, total_tracks: int, total_segments: int = 1):
        """
        Initialize progress tracker.

        Args:
            total_tracks: Total number of tracks in mix
            total_segments: Total number of segments (default 1 for non-segmented)
        """
        self.total_tracks = total_tracks
        self.total_segments = total_segments
        self.current_segment = 0
        self.current_track = 0
        self.start_time = time.time()
        self.segment_start_time = time.time()
        self.track_status: Dict[int, str] = {}  # track_idx -> "pending" | "rendering" | "complete"
        self.phase = "initializing"
        self.output_path: Optional[str] = None
        self.segment_render_times: Dict[int, float] = {}  # segment_idx -> render_time_sec

    def set_output_path(self, path: str):
        """Set output file path for progress display."""
        self.output_path = path

    def start_segment(self, segment_idx: int, num_tracks: int):
        """Begin rendering a segment."""
        self.current_segment = segment_idx
        self.segment_start_time = time.time()
        self.phase = "rendering_segment"
        for i in range(num_tracks):
            self.track_status[i] = "pending"
        self._render()

    def update_track(self, track_idx: int, status: str):
        """Update track status."""
        self.track_status[track_idx] = status
        self.current_track = track_idx
        self._render()

    def complete_segment(self, segment_idx: int):
        """Mark segment as complete."""
        elapsed = time.time() - self.segment_start_time
        self.segment_render_times[segment_idx] = elapsed
        self._render()

    def complete_concatenation(self):
        """Mark concatenation phase as complete."""
        self.phase = "complete"
        self._render()

    def _render(self):
        """Render progress display to terminal."""
        # Clear screen and move cursor to top
        os.system("clear" if os.name != "nt" else "cls")

        # ASCII art header
        print("╔════════════════════════════════════════════════════════════════════╗")
        print("║         🎵 AutoDJ Mix Rendering Wizard 🎧                         ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        print()

        # Overall progress
        elapsed = time.time() - self.start_time

        if self.total_segments == 1:
            # Non-segmented render
            track_pct = (len([s for s in self.track_status.values() if s == "complete"]) / max(self.total_tracks, 1)) * 100
            phase_display = "Rendering Mix"
        else:
            # Segmented render
            completed_segments = len(self.segment_render_times)
            segment_pct = (completed_segments / self.total_segments) * 100
            phase_display = f"Rendering Segment {self.current_segment + 1}/{self.total_segments}"
            track_pct = (len([s for s in self.track_status.values() if s == "complete"]) / max(len(self.track_status), 1)) * 100

        print(f"  Phase: {phase_display}")
        print(f"  Progress: {self._progress_bar(track_pct, width=50)}")
        print(f"  Elapsed: {self._format_time(elapsed)}")
        print()

        # Segment details
        if self.total_segments > 1:
            print("  ┌─ Current Segment Tracks ─────────────────────────────────────┐")
        else:
            print("  ┌─ Tracks ─────────────────────────────────────────────────────┐")

        # Show track status (max 15 per screen)
        tracks_to_show = sorted(self.track_status.items())[-15:]
        for track_idx, status in tracks_to_show:
            icon = self._status_icon(status)
            print(f"  │  {icon} Track {track_idx + 1}")

        if len(self.track_status) > 15:
            remaining = len(self.track_status) - 15
            print(f"  │  ... and {remaining} more tracks")

        print("  └───────────────────────────────────────────────────────────────┘")
        print()

        # System stats
        print("  System:")
        mem_str = self._get_memory_usage()
        print(f"    Memory: {mem_str}")
        print(f"    Output: {self._get_output_size()}")

        # If we have segment render times, show them
        if self.segment_render_times:
            print()
            print("  Segment Timings:")
            for seg_idx, render_time in sorted(self.segment_render_times.items()):
                avg_per_track = render_time / max(len(self.track_status), 1) if self.track_status else 0
                print(f"    Segment {seg_idx}: {render_time:.1f}s "
                      f"({avg_per_track:.2f}s per track)")

        print()
        print("  Status: Running... (Press Ctrl+C to cancel)")

    def _progress_bar(self, percent: float, width: int = 50) -> str:
        """Generate ASCII progress bar."""
        filled = int((percent / 100) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent:.1f}%"

    def _status_icon(self, status: str) -> str:
        """Get status icon."""
        icons = {
            "pending": "⏳",
            "rendering": "▶️ ",
            "complete": "✅",
        }
        return icons.get(status, "❓")

    def _format_time(self, seconds: float) -> str:
        """Format elapsed time as MM:SS."""
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _get_memory_usage(self) -> str:
        """Get current memory usage estimate."""
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            return f"{mem_mb:.1f} / 512 MiB"
        except Exception:
            return "N/A / 512 MiB"

    def _get_output_size(self) -> str:
        """Get current output file size."""
        try:
            if self.output_path:
                from pathlib import Path
                if Path(self.output_path).exists():
                    size_bytes = Path(self.output_path).stat().st_size
                    size_mb = size_bytes / (1024 * 1024)
                    return f"{size_mb:.1f} MB"
        except Exception:
            pass
        return "0 MB"


class SimpleProgressTracker:
    """Simple text-based progress tracker (for non-interactive environments)."""

    def __init__(self, total_tracks: int, total_segments: int = 1):
        """Initialize simple progress tracker."""
        self.total_tracks = total_tracks
        self.total_segments = total_segments
        self.current_segment = 0
        self.completed_segments = 0
        self.start_time = time.time()

    def start_segment(self, segment_idx: int, num_tracks: int):
        """Log segment start."""
        self.current_segment = segment_idx
        logger.info(
            f"Starting segment {segment_idx + 1}/{self.total_segments} "
            f"({num_tracks} tracks)"
        )

    def update_track(self, track_idx: int, status: str):
        """Log track update."""
        if status == "complete":
            logger.debug(f"Track {track_idx + 1} rendering complete")

    def complete_segment(self, segment_idx: int):
        """Log segment completion."""
        self.completed_segments += 1
        elapsed = time.time() - self.start_time
        logger.info(
            f"Segment {segment_idx + 1}/{self.total_segments} complete "
            f"(elapsed: {elapsed:.1f}s)"
        )

    def complete_concatenation(self):
        """Log concatenation completion."""
        elapsed = time.time() - self.start_time
        logger.info(f"Rendering complete (total: {elapsed:.1f}s)")

    def set_output_path(self, path: str):
        """Set output path (unused in simple tracker)."""
        pass


def get_progress_tracker(
    total_tracks: int,
    total_segments: int = 1,
    interactive: bool = True,
) -> "WizardProgressTracker":
    """
    Factory function to get appropriate progress tracker.

    Args:
        total_tracks: Total tracks in mix
        total_segments: Total segments (1 = non-segmented)
        interactive: If True, use wizard UI; if False, use simple logger

    Returns:
        WizardProgressTracker or SimpleProgressTracker instance
    """
    if not interactive or not sys.stdout.isatty():
        return SimpleProgressTracker(total_tracks, total_segments)

    return WizardProgressTracker(total_tracks, total_segments)
