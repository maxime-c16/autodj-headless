"""
Liquidsoap DSP code generator for DJ EQ automation.

Converts detected EQ opportunities into Liquidsoap DSP filter chains
that can be applied to audio tracks in real-time or offline.

Per DJ_EQ_RESEARCH.md and DJ_EQ_AUTOMATION.md:
- Bass cut: eqffmpeg.bass() with -6 to -9dB reduction
- High swap: eqffmpeg.high() with -3 to -6dB reduction  
- Filter sweep: low-pass filter sweep (gradual opening)
- Three-band blend: simultaneous band reduction with envelope
- Bass swap: bass-only energy management

All cuts are:
- Bar-aligned (start/end at bar boundaries)
- Enveloped (attack/hold/release)
- Return to neutral (0dB) after effect
- Time-varying (automation curves)
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import math

from autodj.render.eq_automation import (
    EQOpportunity,
    EQCutType,
    FrequencyBand,
    EQEnvelope,
    EQAutomationEngine,
)

logger = logging.getLogger(__name__)


class EQLiquidsoap:
    """
    Converts detected EQ opportunities into Liquidsoap DSP code.
    
    Responsibilities:
    1. Convert bar positions → sample/time positions
    2. Generate envelope automation curves (attack/hold/release)
    3. Create DSP filter code for each opportunity type
    4. Return complete Liquidsoap function ready to insert into render script
    
    Output format: Liquidsoap function definition that can be wrapped around audio:
    
        # In render.liq, before sequence:
        eq_dsp = fun(s) -> eq_bass_cut_at_bar_12(s)  # Or whatever the function is
        
        # Then in sequence:
        eq_dsp(track_1) |> audio_processing_chain
    """
    
    # Liquidsoap eqffmpeg frequency limits and ranges
    # Based on empirical testing of eqffmpeg module
    EQFFMPEG_LIMITS = {
        'bass_freq_min': 20,      # Hz
        'bass_freq_max': 500,     # Hz
        'mid_freq_min': 100,      # Hz
        'mid_freq_max': 5000,     # Hz
        'high_freq_min': 1000,    # Hz
        'high_freq_max': 20000,   # Hz
    }
    
    # Standard 3-band DJ EQ frequencies (from DJ_EQ_RESEARCH.md)
    FREQ_BANDS = {
        'low': (60, 120),         # Bass/kick
        'mid': (300, 1000),       # Personality/vocals
        'high': (3000, 12000),    # Shine/brightness
    }
    
    def __init__(self, bpm: float, sample_rate: int = 44100):
        """
        Initialize Liquidsoap DSP generator.
        
        Args:
            bpm: Track BPM
            sample_rate: Audio sample rate (Hz)
        """
        self.bpm = bpm
        self.sample_rate = sample_rate
        self.seconds_per_bar = 240.0 / bpm
        self.samples_per_bar = int(self.seconds_per_bar * sample_rate)
        
        logger.debug(
            f"EQ Liquidsoap DSP generator: BPM={bpm}, "
            f"samples/bar={self.samples_per_bar}"
        )
    
    def generate_dsp_chain(
        self,
        opportunities: List[EQOpportunity],
        track_duration_bars: int,
        track_name: str = "unnamed",
    ) -> str:
        """
        Generate Liquidsoap DSP code that applies all EQ opportunities.
        
        Args:
            opportunities: List of detected EQ opportunities
            track_duration_bars: Total bars in track (for bounds checking)
            track_name: Track name (for comment documentation)
        
        Returns:
            Complete Liquidsoap function definition as a string
            
        Example output:
            let eq_dsp_track_1 = fun(s) ->
              # EQ automation for: Artist - Title
              # 3 opportunities detected
              s
              |> dj_bass_cut(magnitude_db=-8.0, bar=12, hold_bars=2)
              |> dj_filter_sweep(start_freq=2000, end_freq=20000, bar=0, duration_bars=16)
              |> dj_high_swap(magnitude_db=-4.5, bar=8, hold_bars=4)
            
            # Usage: eq_dsp_track_1(audio_source)
        """
        if not opportunities:
            # No EQ opportunities: return identity function
            return self._generate_identity_dsp(track_name)
        
        # Sort by bar position for logical reading
        opportunities = sorted(opportunities, key=lambda x: x.bar)
        
        lines = []
        lines.append(f"# EQ automation DSP for: {track_name}")
        lines.append(f"# {len(opportunities)} EQ opportunities detected")
        lines.append("")
        lines.append("let eq_dsp = fun(s) ->")
        lines.append("  s")
        
        for opp in opportunities:
            dsp_filter = self._generate_single_filter(opp, track_duration_bars)
            if dsp_filter:
                for line in dsp_filter.split('\n'):
                    lines.append(f"  {line}")
        
        lines.append("")
        lines.append("eq_dsp")  # Return the function
        
        return '\n'.join(lines)
    
    def _generate_identity_dsp(self, track_name: str) -> str:
        """Generate identity function (no-op DSP) when no opportunities."""
        return (
            f"# No EQ opportunities for: {track_name}\n"
            "let eq_dsp = fun(s) -> s\n"
            "eq_dsp"
        )
    
    def _generate_single_filter(
        self,
        opportunity: EQOpportunity,
        track_duration_bars: int,
    ) -> Optional[str]:
        """
        Generate Liquidsoap code for a single EQ opportunity.
        
        Args:
            opportunity: Single EQ opportunity
            track_duration_bars: Track length in bars (for bounds checking)
        
        Returns:
            Liquidsoap pipe expression or None if invalid
        """
        # Bounds check
        if opportunity.bar < 0 or opportunity.bar >= track_duration_bars:
            logger.warning(
                f"EQ opportunity out of bounds: bar {opportunity.bar} "
                f"in {track_duration_bars}-bar track. Skipping."
            )
            return None
        
        end_bar = opportunity.bar + opportunity.phrase_length_bars
        if end_bar > track_duration_bars:
            # Truncate to track length
            logger.debug(
                f"EQ opportunity extends past track end: "
                f"bar {opportunity.bar}+{opportunity.phrase_length_bars} in "
                f"{track_duration_bars}-bar track. Truncating."
            )
            opportunity.phrase_length_bars = track_duration_bars - opportunity.bar
        
        # Route to appropriate generator based on cut type
        match opportunity.cut_type:
            case EQCutType.BASS_CUT:
                return self._gen_bass_cut(opportunity)
            case EQCutType.HIGH_SWAP:
                return self._gen_high_swap(opportunity)
            case EQCutType.FILTER_SWEEP:
                return self._gen_filter_sweep(opportunity)
            case EQCutType.THREE_BAND_BLEND:
                return self._gen_three_band_blend(opportunity)
            case EQCutType.BASS_SWAP:
                return self._gen_bass_swap(opportunity)
            case _:
                logger.warning(f"Unknown EQ cut type: {opportunity.cut_type}")
                return None
    
    def _gen_bass_cut(self, opp: EQOpportunity) -> str:
        """
        Generate bass cut filter.
        
        Uses eqffmpeg.bass() to reduce kick/bass frequencies.
        Envelope: Instant attack, hold for duration, snap back to neutral.
        """
        bar_to_sec = self.seconds_per_bar
        start_sec = opp.bar * bar_to_sec
        attack_sec = opp.envelope.attack_ms / 1000.0
        hold_sec = opp.envelope.hold_bars * bar_to_sec
        release_sec = opp.envelope.release_ms / 1000.0
        
        freq_hz = self.FREQ_BANDS['low'][0]  # 60 Hz default
        magnitude_db = opp.magnitude_db
        
        return (
            f"|> dj_bass_cut(\n"
            f"    magnitude_db={magnitude_db},\n"
            f"    freq_hz={freq_hz},\n"
            f"    start_sec={start_sec:.3f},\n"
            f"    attack_sec={attack_sec:.3f},\n"
            f"    hold_sec={hold_sec:.3f},\n"
            f"    release_sec={release_sec:.3f},\n"
            f"    reason=\"{opp.reason}\"\n"
            f"  )"
        )
    
    def _gen_high_swap(self, opp: EQOpportunity) -> str:
        """
        Generate high-frequency reduction filter.
        
        Uses eqffmpeg.high() to reduce brightness/harshness.
        Envelope: Gradual fade in, hold, gradual fade out.
        """
        bar_to_sec = self.seconds_per_bar
        start_sec = opp.bar * bar_to_sec
        attack_sec = opp.envelope.attack_ms / 1000.0
        hold_sec = opp.envelope.hold_bars * bar_to_sec
        release_sec = opp.envelope.release_ms / 1000.0
        
        freq_hz = self.FREQ_BANDS['high'][0]  # 3000 Hz default
        magnitude_db = opp.magnitude_db
        
        return (
            f"|> dj_high_swap(\n"
            f"    magnitude_db={magnitude_db},\n"
            f"    freq_hz={freq_hz},\n"
            f"    start_sec={start_sec:.3f},\n"
            f"    attack_sec={attack_sec:.3f},\n"
            f"    hold_sec={hold_sec:.3f},\n"
            f"    release_sec={release_sec:.3f},\n"
            f"    reason=\"{opp.reason}\"\n"
            f"  )"
        )
    
    def _gen_filter_sweep(self, opp: EQOpportunity) -> str:
        """
        Generate low-pass filter sweep.
        
        Opens gradually from muffled (low freq) to bright (high freq).
        Uses low-pass automation to create tension-building effect.
        """
        bar_to_sec = self.seconds_per_bar
        start_sec = opp.bar * bar_to_sec
        attack_sec = opp.envelope.attack_ms / 1000.0
        hold_sec = opp.envelope.hold_bars * bar_to_sec
        release_sec = opp.envelope.release_ms / 1000.0
        
        # Filter sweep: start closed (muffled), gradually open
        start_freq = 2000.0    # Start muffled at 2kHz
        end_freq = 20000.0     # Open to full spectrum
        
        return (
            f"|> dj_filter_sweep(\n"
            f"    start_freq_hz={start_freq},\n"
            f"    end_freq_hz={end_freq},\n"
            f"    start_sec={start_sec:.3f},\n"
            f"    attack_sec={attack_sec:.3f},\n"
            f"    hold_sec={hold_sec:.3f},\n"
            f"    release_sec={release_sec:.3f},\n"
            f"    reason=\"{opp.reason}\"\n"
            f"  )"
        )
    
    def _gen_three_band_blend(self, opp: EQOpportunity) -> str:
        """
        Generate three-band simultaneous blend.
        
        Reduces all three bands together for smooth transitions.
        Gradual envelopes on attack and release.
        """
        bar_to_sec = self.seconds_per_bar
        start_sec = opp.bar * bar_to_sec
        attack_sec = opp.envelope.attack_ms / 1000.0
        hold_sec = opp.envelope.hold_bars * bar_to_sec
        release_sec = opp.envelope.release_ms / 1000.0
        
        # Same magnitude on all three bands
        magnitude_db = opp.magnitude_db
        
        return (
            f"|> dj_three_band_blend(\n"
            f"    magnitude_db={magnitude_db},\n"
            f"    start_sec={start_sec:.3f},\n"
            f"    attack_sec={attack_sec:.3f},\n"
            f"    hold_sec={hold_sec:.3f},\n"
            f"    release_sec={release_sec:.3f},\n"
            f"    reason=\"{opp.reason}\"\n"
            f"  )"
        )
    
    def _gen_bass_swap(self, opp: EQOpportunity) -> str:
        """
        Generate bass swap filter.
        
        Quick bass reduction for energy management.
        Similar to bass_cut but with different default envelope.
        """
        bar_to_sec = self.seconds_per_bar
        start_sec = opp.bar * bar_to_sec
        attack_sec = opp.envelope.attack_ms / 1000.0
        hold_sec = opp.envelope.hold_bars * bar_to_sec
        release_sec = opp.envelope.release_ms / 1000.0
        
        freq_hz = self.FREQ_BANDS['low'][0]  # 60 Hz default
        magnitude_db = opp.magnitude_db
        
        return (
            f"|> dj_bass_swap(\n"
            f"    magnitude_db={magnitude_db},\n"
            f"    freq_hz={freq_hz},\n"
            f"    start_sec={start_sec:.3f},\n"
            f"    attack_sec={attack_sec:.3f},\n"
            f"    hold_sec={hold_sec:.3f},\n"
            f"    release_sec={release_sec:.3f},\n"
            f"    reason=\"{opp.reason}\"\n"
            f"  )"
        )
    
    def generate_liquidsoap_helpers(self) -> str:
        """
        Generate Liquidsoap helper function library for EQ DSP.
        
        These functions must be included in the Liquidsoap script
        before the main sequence to enable EQ automation.
        
        Returns:
            Complete Liquidsoap code with all helper functions
        """
        return self._LIQUIDSOAP_HELPERS_TEMPLATE
    
    # Large Liquidsoap template for helper functions
    _LIQUIDSOAP_HELPERS_TEMPLATE = '''
# ============================================================================
# DJ EQ Automation Helper Functions for Liquidsoap
# Generated by EQLiquidsoap
# ============================================================================
# These functions implement professional DJ EQ techniques with proper
# envelopes, return-to-neutral guarantee, and bar-aligned timing.
# ============================================================================

# Utility: Linear interpolation between values
def dj_lerp(start, end, t) =
  if t <= 0.0 then start
  elsif t >= 1.0 then end
  else begin start + (end - start) * t end
  end

# Utility: Smooth fade (sine curve for natural feel)
def dj_ease_in_out(t) =
  # Sine easing: smoother than linear
  sin(math.pi * (t - 0.5)) / 2.0 + 0.5

# Utility: Linear attack/release envelope
# Returns 0.0-1.0 envelope value at time t (in seconds)
# event_start: when event starts (seconds)
# attack_dur: attack duration (seconds)  
# hold_dur: hold duration (seconds)
# release_dur: release duration (seconds)
def dj_envelope_linear(event_start, attack_dur, hold_dur, release_dur, sr) =
  fun(t) ->
    elapsed = t -. event_start
    if elapsed < 0.0 then 0.0
    elsif elapsed < attack_dur then
      # Attack phase: ramp 0->1 over attack_dur
      if attack_dur == 0.0 then 1.0
      else elapsed /. attack_dur
      end
    elsif elapsed < attack_dur +. hold_dur then
      # Hold phase: stay at 1.0
      1.0
    elsif elapsed < attack_dur +. hold_dur +. release_dur then
      # Release phase: ramp 1->0 over release_dur
      release_progress = (elapsed -. attack_dur -. hold_dur) /. release_dur
      1.0 -. release_progress
    else
      # Complete: back to neutral
      0.0
    end

# ============================================================================
# DJ EQ FILTERS
# ============================================================================

# Bass Cut: Reduce kick/bass frequencies
# Uses eqffmpeg.bass() with automation envelope
def dj_bass_cut(
  s, 
  magnitude_db=(-8),        # Cut depth (negative)
  freq_hz=60,              # Center frequency (Hz)
  start_sec=0.0,           # When to start (seconds)
  attack_sec=0.0,          # Attack duration (seconds)
  hold_sec=0.0,            # Hold duration (seconds)
  release_sec=0.0,         # Release duration (seconds)
  reason=""
) =
  # Create time-varying gain envelope
  sr = int(float_of_int(audio_frame_duration()) * float(request.duration()))
  gain_envelope = dj_envelope_linear(start_sec, attack_sec, hold_sec, release_sec, sr)
  
  # Apply eqffmpeg.bass with animated gain
  s
  |> eqffmpeg.bass(
    freq=freq_hz,
    gain=fun(t) ->
      progress = gain_envelope(t)
      magnitude_db *. progress  # Animate 0 -> magnitude_db -> 0
  )

# High Swap: Reduce brightness/harshness in hi-hats and cymbals
# Uses eqffmpeg.high() with automation envelope
def dj_high_swap(
  s,
  magnitude_db=(-4.5),     # Cut depth (negative)
  freq_hz=3000,            # Center frequency (Hz)
  start_sec=0.0,           # When to start (seconds)
  attack_sec=0.2,          # Attack duration (seconds)
  hold_sec=0.0,            # Hold duration (seconds)
  release_sec=0.2,         # Release duration (seconds)
  reason=""
) =
  # Create time-varying gain envelope
  sr = int(float_of_int(audio_frame_duration()) * float(request.duration()))
  gain_envelope = dj_envelope_linear(start_sec, attack_sec, hold_sec, release_sec, sr)
  
  # Apply eqffmpeg.high with animated gain
  s
  |> eqffmpeg.high(
    freq=freq_hz,
    gain=fun(t) ->
      progress = gain_envelope(t)
      magnitude_db *. progress  # Animate 0 -> magnitude_db -> 0
  )

# Filter Sweep: Low-pass sweep from muffled to open
# Gradual opening creates "reveal" tension effect
def dj_filter_sweep(
  s,
  start_freq_hz=2000.0,    # Initial LP cutoff (muffled)
  end_freq_hz=20000.0,     # Final LP cutoff (open)
  start_sec=0.0,           # When to start (seconds)
  attack_sec=0.1,          # Attack duration (seconds)
  hold_sec=0.0,            # Hold duration (seconds)
  release_sec=0.2,         # Release duration (seconds)
  reason=""
) =
  # Create filter sweep envelope
  sr = int(float_of_int(audio_frame_duration()) * float(request.duration()))
  sweep_envelope = dj_envelope_linear(start_sec, attack_sec, hold_sec, release_sec, sr)
  
  # Apply low-pass filter with animated cutoff
  s
  |> filter.low_pass(
    frequency=fun(t) ->
      progress = sweep_envelope(t)
      # Animate start_freq_hz -> end_freq_hz
      start_freq_hz +. (end_freq_hz -. start_freq_hz) *. progress
  )

# Three-Band Blend: Reduce all three bands simultaneously
# Creates smooth transition between sections
def dj_three_band_blend(
  s,
  magnitude_db=(-6),       # Cut depth on all three bands
  start_sec=0.0,           # When to start (seconds)
  attack_sec=0.5,          # Attack duration (seconds)
  hold_sec=0.0,            # Hold duration (seconds)
  release_sec=0.5,         # Release duration (seconds)
  reason=""
) =
  # Create time-varying gain envelope
  sr = int(float_of_int(audio_frame_duration()) * float(request.duration()))
  gain_envelope = dj_envelope_linear(start_sec, attack_sec, hold_sec, release_sec, sr)
  
  # Apply all three bands with same envelope
  s
  |> eqffmpeg.bass(freq=60, gain=fun(t) -> magnitude_db *. gain_envelope(t))
  |> eqffmpeg(freq=500, gain=fun(t) -> magnitude_db *. gain_envelope(t))
  |> eqffmpeg.high(freq=3000, gain=fun(t) -> magnitude_db *. gain_envelope(t))

# Bass Swap: Quick bass reduction for energy transitions
# Similar to bass_cut but shorter, punchier envelope
def dj_bass_swap(
  s,
  magnitude_db=(-7),       # Cut depth (negative)
  freq_hz=60,              # Center frequency (Hz)
  start_sec=0.0,           # When to start (seconds)
  attack_sec=0.05,         # Quick attack (seconds)
  hold_sec=0.0,            # Hold duration (seconds)
  release_sec=0.05,        # Quick release (seconds)
  reason=""
) =
  # Create time-varying gain envelope
  sr = int(float_of_int(audio_frame_duration()) * float(request.duration()))
  gain_envelope = dj_envelope_linear(start_sec, attack_sec, hold_sec, release_sec, sr)
  
  # Apply eqffmpeg.bass with animated gain
  s
  |> eqffmpeg.bass(
    freq=freq_hz,
    gain=fun(t) ->
      progress = gain_envelope(t)
      magnitude_db *. progress  # Animate 0 -> magnitude_db -> 0
  )

# ============================================================================
'''
