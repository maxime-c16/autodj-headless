"""
Phase 4: Unified DJ Analysis Pipeline
=======================================

Integrates all analysis phases into a single pipeline:
- Phase 2: Harmonic analysis (Camelot wheel compatibility)
- Phase 3: Spectral analysis (frequency content, smart cues)
- Phase 4: Loudness measurement (ITU-R BS.1770-4 LUFS)
- Phase 4: Adaptive EQ design (spectral-aware equalization)
- Phase 1: BPM detection (aubio/essentia)

Provides batch processing with FFT caching, memory management,
and comprehensive per-track analysis.

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import gc
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.autodj.analyze.audio_loader import AudioCache
from src.autodj.analyze.dsp_config import DSPConfig
from src.autodj.analyze.harmonic import (
    HarmonicMixer,
    determine_compatibility,
    CompatibilityLevel,
)
from src.autodj.analyze.spectral import (
    spectral_characteristics,
    identify_smart_cues,
    analyze_energy_profile,
    SpectralCharacteristics,
    SmartCues,
    EnergyProfile,
)
from src.autodj.analyze.loudness import (
    analyze_loudness,
    LoudnessProfile,
    compute_gain_for_transition,
    TARGET_LUFS_STREAMING,
    TARGET_LUFS_DJ,
)
from src.autodj.analyze.adaptive_eq import (
    design_adaptive_eq,
    get_transition_eq,
    AdaptiveEQProfile,
    TransitionEQ,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Default music library path
DEFAULT_MUSIC_PATH = "/srv/nas/shared"

# Performance budgets (per SPEC.md)
MAX_ANALYSIS_TIME_SEC = 30.0   # Per track
MAX_PIPELINE_TIME_SEC = 120.0  # For full batch

# Memory management
GC_INTERVAL = 3  # Force GC every N tracks


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TrackAnalysis:
    """Complete analysis result for a single track.

    Attributes:
        filepath: Absolute path to audio file
        filename: Just the filename
        duration_seconds: Track duration
        bpm: Detected BPM (from Phase 1 DB or detection)
        camelot_key: Detected key in Camelot notation
        spectral: Phase 3 spectral characteristics
        smart_cues: Phase 3 smart cue points
        loudness: Phase 4 loudness profile
        adaptive_eq: Phase 4 adaptive EQ profile
        analysis_time_sec: Time taken for analysis
        errors: List of non-fatal errors during analysis
    """
    filepath: str
    filename: str = ""
    duration_seconds: float = 0.0
    bpm: Optional[float] = None
    camelot_key: Optional[str] = None
    spectral: Optional[SpectralCharacteristics] = None
    smart_cues: Optional[SmartCues] = None
    loudness: Optional[LoudnessProfile] = None
    adaptive_eq: Optional[AdaptiveEQProfile] = None
    analysis_time_sec: float = 0.0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.filename:
            self.filename = Path(self.filepath).name

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: Dict[str, Any] = {
            "filepath": self.filepath,
            "filename": self.filename,
            "duration_seconds": round(self.duration_seconds, 2),
            "bpm": self.bpm,
            "camelot_key": self.camelot_key,
            "analysis_time_sec": round(self.analysis_time_sec, 2),
        }

        if self.spectral:
            result["spectral"] = {
                "bass_energy": round(self.spectral.bass_energy, 3),
                "mid_energy": round(self.spectral.mid_energy, 3),
                "treble_energy": round(self.spectral.treble_energy, 3),
                "rumble_presence": round(self.spectral.rumble_presence, 3),
                "kick_detected": self.spectral.kick_detected,
                "bassline_present": self.spectral.bassline_present,
            }

        if self.smart_cues:
            result["smart_cues"] = {
                "intro_end": self.smart_cues.intro_end,
                "first_kick": self.smart_cues.first_kick,
                "buildups": self.smart_cues.buildups,
                "drops": self.smart_cues.drops,
                "outro_start": self.smart_cues.outro_start,
                "outro_end": self.smart_cues.outro_end,
            }

        if self.loudness:
            result["loudness"] = self.loudness.to_dict()

        if self.adaptive_eq:
            result["adaptive_eq"] = self.adaptive_eq.to_dict()

        if self.errors:
            result["errors"] = self.errors

        return result


@dataclass
class TransitionAnalysis:
    """Analysis of a transition between two tracks.

    Attributes:
        from_track: Index of outgoing track
        to_track: Index of incoming track
        harmonic_compatibility: Camelot compatibility score (0-5)
        harmonic_technique: Suggested mixing technique
        transition_eq: Adaptive EQ for the transition
        loudness_gain_a_db: Gain adjustment for outgoing track
        loudness_gain_b_db: Gain adjustment for incoming track
        bpm_shift_ratio: BPM ratio between tracks
        recommended_duration_sec: Suggested transition duration
    """
    from_track: int
    to_track: int
    harmonic_compatibility: float = 0.0
    harmonic_technique: str = "hard_cut"
    transition_eq: Optional[TransitionEQ] = None
    loudness_gain_a_db: float = 0.0
    loudness_gain_b_db: float = 0.0
    bpm_shift_ratio: float = 1.0
    recommended_duration_sec: float = 4.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: Dict[str, Any] = {
            "from_track": self.from_track,
            "to_track": self.to_track,
            "harmonic_compatibility": round(self.harmonic_compatibility, 2),
            "harmonic_technique": self.harmonic_technique,
            "loudness_gain_a_db": round(self.loudness_gain_a_db, 1),
            "loudness_gain_b_db": round(self.loudness_gain_b_db, 1),
            "bpm_shift_ratio": round(self.bpm_shift_ratio, 4),
            "recommended_duration_sec": round(self.recommended_duration_sec, 1),
        }
        if self.transition_eq:
            result["transition_eq"] = self.transition_eq.to_dict()
        return result


@dataclass
class SetAnalysis:
    """Complete analysis of a DJ set (multiple tracks + transitions).

    Attributes:
        tracks: Per-track analysis results
        transitions: Transition analysis for adjacent tracks
        optimal_sequence: Recommended track order (indices)
        total_duration_sec: Combined track duration
        avg_compatibility: Average harmonic compatibility score
        analysis_timestamp: When analysis was performed
        total_analysis_time_sec: Total pipeline runtime
    """
    tracks: List[TrackAnalysis] = field(default_factory=list)
    transitions: List[TransitionAnalysis] = field(default_factory=list)
    optimal_sequence: List[int] = field(default_factory=list)
    total_duration_sec: float = 0.0
    avg_compatibility: float = 0.0
    analysis_timestamp: str = ""
    total_analysis_time_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "analysis_timestamp": self.analysis_timestamp,
            "phase": "4 (Unified Pipeline)",
            "track_count": len(self.tracks),
            "total_duration_sec": round(self.total_duration_sec, 2),
            "avg_compatibility": round(self.avg_compatibility, 2),
            "optimal_sequence": self.optimal_sequence,
            "total_analysis_time_sec": round(self.total_analysis_time_sec, 2),
            "tracks": [t.to_dict() for t in self.tracks],
            "transitions": [t.to_dict() for t in self.transitions],
        }


# ============================================================================
# PIPELINE CLASS
# ============================================================================

class DJAnalysisPipeline:
    """
    Unified DJ track analysis pipeline.

    Orchestrates all analysis phases for individual tracks and complete sets.
    Handles memory management, error recovery, and performance tracking.
    """

    def __init__(
        self,
        target_lufs: float = TARGET_LUFS_STREAMING,
        compute_true_peak: bool = True,
        eq_sensitivity: float = 0.7,
        config: Optional[DSPConfig] = None,
    ) -> None:
        """
        Initialize the analysis pipeline.

        Args:
            target_lufs: Target loudness for normalization
            compute_true_peak: Whether to compute true peak (slower)
            eq_sensitivity: EQ correction sensitivity (0.0-1.0)
            config: Optional DSPConfig for global DSP parameters
        """
        self.target_lufs = target_lufs
        self.compute_true_peak = compute_true_peak
        self.eq_sensitivity = eq_sensitivity
        self.config = config or DSPConfig()
        self.audio_cache = AudioCache(sample_rate=self.config.sample_rate)

        logger.debug(
            f"Pipeline initialized: target={target_lufs} LUFS, "
            f"true_peak={compute_true_peak}, eq_sens={eq_sensitivity}, "
            f"sr={self.config.sample_rate}, fft={self.config.fft_size}"
        )

    def analyze_track(
        self,
        filepath: str,
        bpm: Optional[float] = None,
        camelot_key: Optional[str] = None,
    ) -> TrackAnalysis:
        """
        Perform complete analysis on a single track.

        Runs all available phases:
        1. Spectral analysis (Phase 3)
        2. Smart cue detection (Phase 3)
        3. Loudness measurement (Phase 4)
        4. Adaptive EQ design (Phase 4)

        Args:
            filepath: Path to audio file
            bpm: Pre-detected BPM (from Phase 1 DB), None to skip
            camelot_key: Pre-detected key (from Phase 1 DB), None to skip

        Returns:
            TrackAnalysis with all available results

        Raises:
            FileNotFoundError: If audio file doesn't exist
        """
        start_time = time.monotonic()
        analysis = TrackAnalysis(filepath=filepath, bpm=bpm, camelot_key=camelot_key)

        logger.info(f"Analyzing track: {analysis.filename}")

        # Load audio once via cache, share across all modules
        try:
            audio_mono = self.audio_cache.load(filepath, mono=True)
        except Exception as e:
            msg = f"Audio loading failed: {e}"
            logger.warning(msg)
            analysis.errors.append(msg)
            analysis.analysis_time_sec = time.monotonic() - start_time
            return analysis

        # Phase 3: Spectral characteristics
        try:
            analysis.spectral = spectral_characteristics(
                filepath, audio_data=audio_mono, config=self.config,
            )
            logger.debug(
                f"Spectral: bass={analysis.spectral.bass_energy:.2f}, "
                f"mid={analysis.spectral.mid_energy:.2f}, "
                f"treble={analysis.spectral.treble_energy:.2f}"
            )
        except Exception as e:
            msg = f"Spectral analysis failed: {e}"
            logger.warning(msg)
            analysis.errors.append(msg)

        # Phase 3: Smart cues
        try:
            analysis.smart_cues = identify_smart_cues(
                filepath, audio_data=audio_mono, config=self.config,
            )
        except Exception as e:
            msg = f"Smart cue detection failed: {e}"
            logger.warning(msg)
            analysis.errors.append(msg)

        # Phase 4: Loudness (may need stereo; fall back to disk if cached is mono)
        try:
            analysis.loudness = analyze_loudness(
                filepath,
                target_lufs=self.target_lufs,
                compute_true_peak=self.compute_true_peak,
                audio_data=audio_mono,
            )
            analysis.duration_seconds = analysis.loudness.duration_seconds
        except Exception as e:
            msg = f"Loudness analysis failed: {e}"
            logger.warning(msg)
            analysis.errors.append(msg)

        # Phase 4: Adaptive EQ (requires spectral data)
        if analysis.spectral:
            try:
                loudness_comp = 0.0
                if analysis.loudness:
                    loudness_comp = analysis.loudness.target_gain_db

                spectral_data = {
                    "bass_energy": analysis.spectral.bass_energy,
                    "mid_energy": analysis.spectral.mid_energy,
                    "treble_energy": analysis.spectral.treble_energy,
                }
                analysis.adaptive_eq = design_adaptive_eq(
                    spectral_data,
                    loudness_compensation_db=loudness_comp,
                    sensitivity=self.eq_sensitivity,
                )
            except Exception as e:
                msg = f"Adaptive EQ design failed: {e}"
                logger.warning(msg)
                analysis.errors.append(msg)

        analysis.analysis_time_sec = time.monotonic() - start_time

        logger.info(
            f"Track analysis complete: {analysis.filename} "
            f"({analysis.analysis_time_sec:.1f}s)"
        )

        return analysis

    def analyze_set(
        self,
        filepaths: List[str],
        bpms: Optional[List[Optional[float]]] = None,
        keys: Optional[List[Optional[str]]] = None,
    ) -> SetAnalysis:
        """
        Analyze a complete DJ set (multiple tracks + transitions).

        Performs per-track analysis, computes harmonic compatibility matrix,
        finds optimal sequence, and designs transition EQ for each adjacent pair.

        Args:
            filepaths: List of audio file paths
            bpms: Optional pre-detected BPMs (from Phase 1)
            keys: Optional pre-detected Camelot keys (from Phase 1)

        Returns:
            SetAnalysis with all tracks, transitions, and recommendations
        """
        start_time = time.monotonic()

        if bpms is None:
            bpms = [None] * len(filepaths)
        if keys is None:
            keys = [None] * len(filepaths)

        set_analysis = SetAnalysis(
            analysis_timestamp=datetime.utcnow().isoformat() + "Z",
        )

        # Phase 1: Analyze each track
        for i, (fp, bpm, key) in enumerate(zip(filepaths, bpms, keys)):
            logger.info(f"Set analysis [{i+1}/{len(filepaths)}]: {Path(fp).name}")

            track = self.analyze_track(fp, bpm=bpm, camelot_key=key)
            set_analysis.tracks.append(track)

            # Memory management per SPEC.md: clear audio cache after each track
            self.audio_cache.clear()
            if (i + 1) % GC_INTERVAL == 0:
                gc.collect()

        # Phase 2: Harmonic compatibility (if keys available)
        tracks_with_keys = [
            (i, t) for i, t in enumerate(set_analysis.tracks)
            if t.camelot_key is not None
        ]

        if len(tracks_with_keys) >= 2:
            mixer = HarmonicMixer()
            for i, t in tracks_with_keys:
                mixer.add_track(i, t.filename, t.camelot_key)

            set_analysis.optimal_sequence = mixer.find_optimal_sequence()
        else:
            set_analysis.optimal_sequence = list(range(len(filepaths)))

        # Compute transitions for adjacent tracks in sequence
        sequence = set_analysis.optimal_sequence
        for idx in range(len(sequence) - 1):
            i = sequence[idx]
            j = sequence[idx + 1]

            track_a = set_analysis.tracks[i]
            track_b = set_analysis.tracks[j]

            transition = self._analyze_transition(track_a, track_b, i, j)
            set_analysis.transitions.append(transition)

        # Aggregate statistics
        set_analysis.total_duration_sec = sum(
            t.duration_seconds for t in set_analysis.tracks
        )
        if set_analysis.transitions:
            set_analysis.avg_compatibility = np.mean([
                t.harmonic_compatibility for t in set_analysis.transitions
            ])

        set_analysis.total_analysis_time_sec = time.monotonic() - start_time

        logger.info(
            f"Set analysis complete: {len(filepaths)} tracks, "
            f"{set_analysis.total_analysis_time_sec:.1f}s, "
            f"avg compatibility: {set_analysis.avg_compatibility:.2f}/5.0"
        )

        gc.collect()
        return set_analysis

    def _analyze_transition(
        self,
        track_a: TrackAnalysis,
        track_b: TrackAnalysis,
        idx_a: int,
        idx_b: int,
    ) -> TransitionAnalysis:
        """
        Analyze a single transition between two tracks.

        Computes harmonic compatibility, loudness matching gains,
        BPM shift ratio, and adaptive transition EQ.

        Args:
            track_a: Outgoing track analysis
            track_b: Incoming track analysis
            idx_a: Track A index
            idx_b: Track B index

        Returns:
            TransitionAnalysis with all transition parameters
        """
        transition = TransitionAnalysis(from_track=idx_a, to_track=idx_b)

        # Harmonic compatibility
        if track_a.camelot_key and track_b.camelot_key:
            level, score = determine_compatibility(
                track_a.camelot_key, track_b.camelot_key
            )
            transition.harmonic_compatibility = score

            techniques = {
                CompatibilityLevel.PERFECT: "perfect_mix",
                CompatibilityLevel.EXCELLENT: "smooth_crossfade",
                CompatibilityLevel.GOOD: "careful_crossfade",
                CompatibilityLevel.ACCEPTABLE: "filter_sweep",
                CompatibilityLevel.POOR: "hard_cut",
                CompatibilityLevel.INCOMPATIBLE: "avoid_mixing",
            }
            transition.harmonic_technique = techniques.get(level, "hard_cut")

            # Duration based on compatibility
            duration_map = {
                CompatibilityLevel.PERFECT: 8.0,
                CompatibilityLevel.EXCELLENT: 6.0,
                CompatibilityLevel.GOOD: 4.0,
                CompatibilityLevel.ACCEPTABLE: 3.0,
                CompatibilityLevel.POOR: 2.0,
                CompatibilityLevel.INCOMPATIBLE: 1.0,
            }
            transition.recommended_duration_sec = duration_map.get(level, 4.0)

        # BPM shift
        if track_a.bpm and track_b.bpm:
            transition.bpm_shift_ratio = track_b.bpm / track_a.bpm

        # Loudness matching
        if track_a.loudness and track_b.loudness:
            gain_a, gain_b = compute_gain_for_transition(
                track_a.loudness, track_b.loudness
            )
            transition.loudness_gain_a_db = gain_a
            transition.loudness_gain_b_db = gain_b

        # Transition EQ
        if track_a.adaptive_eq and track_b.adaptive_eq:
            transition.transition_eq = get_transition_eq(
                track_a.adaptive_eq,
                track_b.adaptive_eq,
                duration_seconds=transition.recommended_duration_sec,
            )

        return transition


# ============================================================================
# EXPORT
# ============================================================================

def export_set_analysis_json(
    analysis: SetAnalysis,
    output_path: str,
) -> None:
    """
    Export complete set analysis to JSON.

    Args:
        analysis: SetAnalysis result
        output_path: Output JSON file path
    """
    with open(output_path, "w") as f:
        json.dump(analysis.to_dict(), f, indent=2)

    logger.info(f"Set analysis exported to {output_path}")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def quick_analyze(filepath: str) -> Dict[str, Any]:
    """
    Quick single-track analysis with default settings.

    Args:
        filepath: Path to audio file

    Returns:
        Dict with analysis results
    """
    pipeline = DJAnalysisPipeline()
    result = pipeline.analyze_track(filepath)
    return result.to_dict()


def analyze_dj_set(
    filepaths: List[str],
    output_json: Optional[str] = None,
    target_lufs: float = TARGET_LUFS_STREAMING,
) -> SetAnalysis:
    """
    Analyze a complete DJ set and optionally export to JSON.

    Args:
        filepaths: List of audio file paths
        output_json: Optional output JSON path
        target_lufs: Target loudness for normalization

    Returns:
        SetAnalysis with complete results
    """
    pipeline = DJAnalysisPipeline(target_lufs=target_lufs)
    analysis = pipeline.analyze_set(filepaths)

    if output_json:
        export_set_analysis_json(analysis, output_json)

    return analysis


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    )

    if len(sys.argv) < 2:
        print("Phase 4 Unified Analysis Pipeline")
        print(f"Usage: python -m src.autodj.analyze.pipeline <file1> [file2] ...")
        print(f"Music library: {DEFAULT_MUSIC_PATH}")
        sys.exit(0)

    filepaths = sys.argv[1:]
    print(f"Analyzing {len(filepaths)} tracks...")

    analysis = analyze_dj_set(
        filepaths,
        output_json="data/phase4_analysis.json",
    )

    print(f"\nResults:")
    print(f"  Tracks: {len(analysis.tracks)}")
    print(f"  Duration: {analysis.total_duration_sec:.0f}s")
    print(f"  Avg compatibility: {analysis.avg_compatibility:.2f}/5.0")
    print(f"  Analysis time: {analysis.total_analysis_time_sec:.1f}s")
    print(f"  Optimal sequence: {analysis.optimal_sequence}")
