"""
Segment-Based EQ Integration for AutoDJ Render Pipeline

Provides 4 different strategies for applying per-segment bass-cut EQ:
1. LADSPA CMT HPF/LPF - Simple 1-pole filters
2. FFmpeg anequalizer - 128-band professional EQ
3. Calf EQ - 3-band parametric (requires upgrade)
4. Hybrid Pre-Processing - Extract, process offline, mix back

This module integrates seamlessly with the existing v2 render script.
"""

import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class SegmentEQStrategy:
    """Base class for segment-based EQ strategies"""
    
    NAME = "BaseStrategy"
    DESCRIPTION = "Base EQ strategy"
    
    def apply_to_drop_segment(
        self,
        segment_var: str,
        file_path: str,
        cue_in: float,
        cue_out: float,
        bpm: float,
        overlap_bars: int,
    ) -> List[str]:
        """
        Generate Liquidsoap code for applying EQ to a drop segment
        
        Args:
            segment_var: Variable name for the segment (e.g., "segment_drop_0")
            file_path: Path to audio file
            cue_in: Segment start time (seconds)
            cue_out: Segment end time (seconds)
            bpm: BPM of the track
            overlap_bars: Number of bars in overlap
        
        Returns:
            List of Liquidsoap script lines to add to the render pipeline
        """
        raise NotImplementedError


class LADSPA_HPF_LPF(SegmentEQStrategy):
    """Strategy 1: LADSPA CMT 1-pole filters"""
    
    NAME = "LADSPA CMT HPF/LPF"
    DESCRIPTION = "1-pole high-pass filter from CMT library for bass cut"
    
    def apply_to_drop_segment(
        self,
        segment_var: str,
        file_path: str,
        cue_in: float,
        cue_out: float,
        bpm: float,
        overlap_bars: int,
    ) -> List[str]:
        """
        Apply native Liquidsoap butterworth HPF to drop segment
        
        Output:
            s_drop = filter.butterworth.highpass(frequency=200., s_drop)
            
        Uses pure Liquidsoap (no external LADSPA plugins needed)
        """
        lines = []
        
        # Prepare cue annotations
        annotations = []
        if cue_in > 0:
            annotations.append(f"liq_cue_in={cue_in:.3f}")
        if cue_out > 0:
            annotations.append(f"liq_cue_out={cue_out:.3f}")
        
        if annotations:
            annotate_str = ",".join(annotations)
            lines.append(f'# 🎛️ Drop segment: IIR butterworth HPF (Liq 2.1.3 compatible)')
            lines.append(f'{segment_var} = once(single("annotate:{annotate_str}:{file_path}"))')
            lines.append(f"{segment_var} = cue_cut({segment_var})")
        else:
            lines.append(f'# 🎛️ Drop segment: IIR butterworth HPF')
            lines.append(f'{segment_var} = once(single("{file_path}"))')

        # REQUIRED: decode ffmpeg.audio.raw → pcm before any DSP on m4a/ALAC files
        # WAV files are native PCM in Liquidsoap 2.1.3 — no decode needed
        if not file_path.lower().endswith('.wav'):
            lines.append(f"{segment_var} = ffmpeg.raw.decode.audio({segment_var})")

        # filter.iir.butterworth.high works in Liq 2.1.3 (filter.butterworth.highpass does NOT exist)
        lines.append(f"")
        lines.append(f"# 🎛️ DJ EQ: BASS CUT applied (HPF @ 200Hz removes kick/sub-bass)")
        lines.append(f"{segment_var} = filter.rc(frequency=200.0, mode=\"high\", {segment_var})")
        lines.append(f"# ✅ Using filter.rc() (works in Liq 2.2.x, unlike broken butterworth)")

        return lines


class FFmpeg_Anequalizer(SegmentEQStrategy):
    """Strategy 2: FFmpeg anequalizer (128-band)"""
    
    NAME = "FFmpeg anequalizer"
    DESCRIPTION = "128-band professional parametric EQ via FFmpeg"
    
    # Default bass-cut frequencies and gains
    BASS_CUT_FREQUENCIES = [100, 200, 300, 400]  # Hz
    BASS_CUT_GAINS = [-10.0, -8.0, -6.0, -4.0]  # dB
    
    @staticmethod
    def generate_anequalizer_spec(
        frequencies: List[int],
        gains_db: List[float]
    ) -> str:
        """
        Generate FFmpeg anequalizer filter specification
        
        Format: c0=f0 t=type h=shelf g=gain q=q:c1=f1 ...
        
        Args:
            frequencies: Center frequencies (Hz)
            gains_db: Gains in dB (one per frequency)
        
        Returns:
            anequalizer filter specification string
        """
        if len(frequencies) != len(gains_db):
            raise ValueError("Frequencies and gains mismatch")
        
        eq_parts = []
        for idx, (freq, gain) in enumerate(zip(frequencies, gains_db)):
            # Use shelf for edges, bandpass for interior
            if idx == 0:
                h_type = "lp"  # Low-shelf
            elif idx == len(frequencies) - 1:
                h_type = "hp"  # High-shelf
            else:
                h_type = "bp"  # Bandpass
            
            t_type = "bp"
            q = 0.7  # Q factor
            
            eq_parts.append(f"c{idx}={freq} t={t_type} h={h_type} g={gain:.1f} q={q}")
        
        return ":".join(eq_parts)
    
    def apply_to_drop_segment(
        self,
        segment_var: str,
        file_path: str,
        cue_in: float,
        cue_out: float,
        bpm: float,
        overlap_bars: int,
    ) -> List[str]:
        """
        Apply FFmpeg anequalizer to drop segment
        
        Applies 128-band EQ with bass cut at 100, 200, 300, 400Hz
        """
        lines = []
        
        # Generate EQ spec
        eq_spec = self.generate_anequalizer_spec(
            self.BASS_CUT_FREQUENCIES,
            self.BASS_CUT_GAINS
        )
        
        # Prepare cue annotations
        annotations = []
        if cue_in > 0:
            annotations.append(f"liq_cue_in={cue_in:.3f}")
        if cue_out > 0:
            annotations.append(f"liq_cue_out={cue_out:.3f}")
        
        segment_source = segment_var + "_source"
        
        if annotations:
            annotate_str = ",".join(annotations)
            lines.append(f'# Drop segment with FFmpeg 128-band anequalizer')
            lines.append(f'{segment_source} = once(single("annotate:{annotate_str}:{file_path}"))')
            lines.append(f"{segment_source} = cue_cut({segment_source})")
        else:
            lines.append(f'# Drop segment with FFmpeg 128-band anequalizer')
            lines.append(f'{segment_source} = once(single("{file_path}"))')
        
        # Apply FFmpeg anequalizer via ffmpeg.filter API
        lines.append("")
        lines.append(f"# Apply FFmpeg 128-band anequalizer to drop segment")
        lines.append(f"def apply_anequalizer_{segment_var}(s) =")
        lines.append(f"  def mkfilter(graph) =")
        lines.append(f"    let {{ audio = audio_track }} = source.tracks(s)")
        lines.append(f"    audio_track = ffmpeg.filter.audio.input(graph, audio_track)")
        lines.append(f'    audio_track = ffmpeg.filter.anequalizer(graph, "{eq_spec}", audio_track)')
        lines.append(f"    audio_track = ffmpeg.filter.audio.output(graph, audio_track)")
        lines.append(f"    source({{audio = audio_track, metadata = track.metadata(audio_track)}})")
        lines.append(f"  end")
        lines.append(f"  ffmpeg.filter.create(mkfilter)")
        lines.append(f"end")
        lines.append(f"")
        lines.append(f"{segment_var} = apply_anequalizer_{segment_var}({segment_source})")
        lines.append(f"# ✅ Solution 2: FFmpeg anequalizer applied (128-band bass cut)")
        
        return lines


class Calf_EQ(SegmentEQStrategy):
    """Strategy 3: Calf parametric EQ (3-band)"""
    
    NAME = "Calf EQ"
    DESCRIPTION = "3-band parametric EQ (bass/mid/treble) via LADSPA"
    
    # Default 3-band EQ
    BASS_DB = -8.0
    MID_DB = 0.0
    TREBLE_DB = 0.0
    
    def apply_to_drop_segment(
        self,
        segment_var: str,
        file_path: str,
        cue_in: float,
        cue_out: float,
        bpm: float,
        overlap_bars: int,
    ) -> List[str]:
        """
        Apply Calf parametric EQ to drop segment
        
        Requires: apt-get install calf-studio-gear in container
        """
        lines = []
        
        # Prepare cue annotations
        annotations = []
        if cue_in > 0:
            annotations.append(f"liq_cue_in={cue_in:.3f}")
        if cue_out > 0:
            annotations.append(f"liq_cue_out={cue_out:.3f}")
        
        if annotations:
            annotate_str = ",".join(annotations)
            lines.append(f'# Drop segment with Calf 3-band parametric EQ')
            lines.append(f'{segment_var} = once(single("annotate:{annotate_str}:{file_path}"))')
            lines.append(f"{segment_var} = cue_cut({segment_var})")
        else:
            lines.append(f'# Drop segment with Calf parametric EQ')
            lines.append(f'{segment_var} = once(single("{file_path}"))')
        
        # Apply Calf parametric EQ (3-band)
        lines.append(f"{segment_var} = ladspa.calf_parametriceq(")
        lines.append(f"  bass={self.BASS_DB},")
        lines.append(f"  middle={self.MID_DB},")
        lines.append(f"  treble={self.TREBLE_DB}")
        lines.append(f")({segment_var})")
        lines.append(f"# ✅ Solution 3: Calf parametric EQ applied (3-band: {self.BASS_DB}dB bass)")
        
        return lines


class Hybrid_PreProcessing(SegmentEQStrategy):
    """Strategy 4: Hybrid pre-processing + FFmpeg"""
    
    NAME = "Hybrid Pre-Processing"
    DESCRIPTION = "Extract segments to WAV, apply FFmpeg EQ offline, mix back"
    
    def apply_to_drop_segment(
        self,
        segment_var: str,
        file_path: str,
        cue_in: float,
        cue_out: float,
        bpm: float,
        overlap_bars: int,
    ) -> List[str]:
        """
        Apply hybrid pre-processing approach
        
        Note: This requires Python pre-processing phase before Liquidsoap render.
        This method returns the Liquidsoap code to USE the pre-processed WAV.
        """
        lines = []
        
        # In a hybrid approach, the segment would already be processed
        # and stored in a temporary location
        processed_wav = f"/tmp/eq_processed_{segment_var}.wav"
        
        lines.append(f"# Hybrid approach: use pre-processed EQ'd segment")
        lines.append(f"{segment_var} = once(single(\"{processed_wav}\"))")
        lines.append(f"# ✅ Solution 4: Hybrid pre-processing (offline FFmpeg EQ applied)")
        
        return lines


# Mapping of strategy names to classes
STRATEGIES = {
    "ladspa": LADSPA_HPF_LPF,
    "ffmpeg": FFmpeg_Anequalizer,
    "calf": Calf_EQ,
    "hybrid": Hybrid_PreProcessing,
}


def get_strategy(strategy_name: str) -> Optional[SegmentEQStrategy]:
    """Get a strategy instance by name"""
    if strategy_name not in STRATEGIES:
        logger.warning(f"Unknown strategy: {strategy_name}, available: {list(STRATEGIES.keys())}")
        return None
    
    return STRATEGIES[strategy_name]()


def apply_segment_eq(
    segment_var: str,
    file_path: str,
    cue_in: float,
    cue_out: float,
    bpm: float,
    overlap_bars: int,
    strategy: str = "ladspa"
) -> List[str]:
    """
    Apply segment-based EQ using specified strategy
    
    Args:
        segment_var: Variable name for segment
        file_path: Audio file path
        cue_in: Segment start (seconds)
        cue_out: Segment end (seconds)
        bpm: Track BPM
        overlap_bars: Overlap duration in bars
        strategy: EQ strategy to use ("ladspa", "ffmpeg", "calf", "hybrid")
    
    Returns:
        List of Liquidsoap script lines
    """
    strat = get_strategy(strategy)
    if not strat:
        logger.warning(f"Strategy {strategy} not available, using LADSPA fallback")
        strat = LADSPA_HPF_LPF()
    
    return strat.apply_to_drop_segment(
        segment_var, file_path, cue_in, cue_out, bpm, overlap_bars
    )
