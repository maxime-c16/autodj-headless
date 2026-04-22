"""
Phase 2: Bass Cut Control Implementation

Implements professional DJ bass swapping: Apply 50-80% bass frequency cut to 
incoming track during the transition overlap, then gradually unmask the bass.

DJ Reality: Professional DJs NEVER let two basslines play at full volume simultaneously.
Result: Muddy, undefined low-end that feels amateur.

This module handles:
- Bass cut calculation (50-80% depth)
- HPF (High-Pass Filter) generation for Liquidsoap
- Gradual bass unmask timing
- Integration with EQ automation
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List
from enum import Enum

logger = logging.getLogger(__name__)


class BassCutStrategy(Enum):
    """Bass cut application strategies"""
    INSTANT = "instant"          # Full HPF at transition start, unmask over bars
    GRADUAL = "gradual"          # Gradual HPF application + unmask
    CREATIVE = "creative"        # Mids-only phase before drop (advanced)


@dataclass
class BassCutParams:
    """Parameters for bass cut control"""
    # Filter specification
    hpf_frequency: float = 200.0     # High-pass filter cutoff (Hz)
    cut_intensity: float = 0.65      # 0-1 scale (0 = no cut, 1 = full mute)
    strategy: BassCutStrategy = BassCutStrategy.INSTANT
    
    # Timing
    transition_start_seconds: float = 0.0
    transition_duration_bars: int = 16
    bpm: float = 128.0
    unmask_delay_bars: int = 0      # Bars to wait before starting unmask
    unmask_duration_bars: int = 8   # How many bars to unmask over
    
    # Validation
    enable_bass_cut: bool = True
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate bass cut parameters
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []
        
        if self.hpf_frequency < 50 or self.hpf_frequency > 500:
            errors.append("HPF frequency out of range (50-500 Hz)")
        
        if self.cut_intensity < 0 or self.cut_intensity > 1.0:
            errors.append("Cut intensity out of range (0-1)")
        
        if self.unmask_delay_bars > self.transition_duration_bars:
            errors.append("Unmask delay exceeds transition duration")
        
        if self.bpm < 40 or self.bpm > 240:
            errors.append("BPM out of typical range (40-240)")
        
        is_valid = len(errors) == 0
        error_msg = "; ".join(errors) if errors else None
        
        return is_valid, error_msg
    
    def get_transition_duration_seconds(self) -> float:
        """Calculate transition duration in seconds"""
        return (self.transition_duration_bars * 60.0) / self.bpm
    
    def get_unmask_start_seconds(self) -> float:
        """Calculate when unmask begins (relative to transition start)"""
        delay_sec = (self.unmask_delay_bars * 60.0) / self.bpm
        return delay_sec
    
    def get_unmask_duration_seconds(self) -> float:
        """Calculate unmask duration in seconds"""
        return (self.unmask_duration_bars * 60.0) / self.bpm


class BassCutEngine:
    """
    Generates bass cut specifications for DJ transitions
    
    Usage:
        engine = BassCutEngine()
        spec = engine.create_bass_cut_spec(
            transition_start=180.0,
            transition_duration_bars=16,
            bpm=128,
        )
        liquidsoap_filter = engine.generate_liquidsoap_filter(spec)
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def create_bass_cut_spec(
        self,
        transition_start: float,
        transition_duration_bars: int,
        bpm: float,
        strategy: BassCutStrategy = BassCutStrategy.INSTANT,
        cut_intensity: float = 0.65,  # 65% = standard DJ bass cut
        hpf_frequency: float = 200.0,
        unmask_delay_bars: int = 4,   # Don't start unmasking immediately
    ) -> BassCutParams:
        """
        Create a complete bass cut specification
        
        Args:
            transition_start: When transition begins (seconds)
            transition_duration_bars: Length of transition (bars)
            bpm: BPM of the track
            strategy: How to apply the cut
            cut_intensity: 0-1 scale, 0.65 typical (50-80% range)
            hpf_frequency: HPF cutoff in Hz (typical 200 Hz)
            unmask_delay_bars: Delay before starting bass unmask
        
        Returns:
            BassCutParams instance
        """
        params = BassCutParams(
            hpf_frequency=hpf_frequency,
            cut_intensity=cut_intensity,
            strategy=strategy,
            transition_start_seconds=transition_start,
            transition_duration_bars=transition_duration_bars,
            bpm=bpm,
            unmask_delay_bars=unmask_delay_bars,
            unmask_duration_bars=transition_duration_bars - unmask_delay_bars,
            enable_bass_cut=True,
        )
        
        is_valid, error = params.validate()
        if not is_valid:
            self.logger.warning(f"Bass cut validation failed: {error}")
        
        return params
    
    def generate_liquidsoap_filter(
        self,
        params: BassCutParams,
    ) -> List[str]:
        """
        Generate Liquidsoap filter code for bass cut
        
        Returns:
            List of Liquidsoap script lines
        """
        script_lines = []
        
        script_lines.append("# Phase 2: Bass Cut Control")
        script_lines.append(f"# HPF cutoff: {params.hpf_frequency} Hz")
        script_lines.append(f"# Cut intensity: {params.cut_intensity:.0%}")
        script_lines.append(f"# Transition duration: {params.transition_duration_bars} bars")
        script_lines.append("")
        
        # For Liquidsoap 2.1.3, we use butterworth high-pass filter
        # Formula: filter.iir.butterworth.high_pass(frequency=Hz, s)
        
        if params.strategy == BassCutStrategy.INSTANT:
            script_lines.extend(self._generate_instant_cut(params))
        elif params.strategy == BassCutStrategy.GRADUAL:
            script_lines.extend(self._generate_gradual_cut(params))
        elif params.strategy == BassCutStrategy.CREATIVE:
            script_lines.extend(self._generate_creative_cut(params))
        
        return script_lines
    
    def _generate_instant_cut(self, params: BassCutParams) -> List[str]:
        """Instant HPF application strategy"""
        lines = []
        lines.append("# Strategy: INSTANT bass cut")
        lines.append("# Apply HPF immediately at transition start")
        lines.append(f"hpf_freq = {params.hpf_frequency}")
        lines.append("incoming_filtered = filter.iir.butterworth.high_pass(")
        lines.append("    frequency=hpf_freq,")
        lines.append("    incoming")
        lines.append(")")
        lines.append("")
        lines.append("# Unmask bass gradually over transition")
        unmask_start = params.get_unmask_start_seconds()
        unmask_duration = params.get_unmask_duration_seconds()
        lines.append(f"# Unmask starts: {unmask_start:.2f}s after transition start")
        lines.append(f"# Unmask duration: {unmask_duration:.2f}s")
        lines.append("# Implementation: Use Liquidsoap #fade() to blend unfiltered")
        lines.append("")
        
        return lines
    
    def _generate_gradual_cut(self, params: BassCutParams) -> List[str]:
        """Gradual HPF application strategy"""
        lines = []
        lines.append("# Strategy: GRADUAL bass cut")
        lines.append("# Gradually apply HPF over first bars, then unmask")
        lines.append("# This is more natural-sounding than instant cut")
        lines.append(f"hpf_freq = {params.hpf_frequency}")
        lines.append(f"cut_intensity = {params.cut_intensity}")
        lines.append("")
        lines.append("# Gradual HPF application (future: envelope control)")
        lines.append("# For now: approximate with instant but mark for enhancement")
        lines.append("incoming_filtered = filter.iir.butterworth.high_pass(")
        lines.append("    frequency=hpf_freq,")
        lines.append("    incoming")
        lines.append(")")
        lines.append("")
        
        return lines
    
    def _generate_creative_cut(self, params: BassCutParams) -> List[str]:
        """Creative EQ strategy - mids-only phase before drop"""
        lines = []
        lines.append("# Strategy: CREATIVE mids-only phase")
        lines.append("# Remove bass AND highs momentarily, leaving muffled mids")
        lines.append("# Just before drop, slam bass back in for energy")
        lines.append(f"hpf_freq = {params.hpf_frequency}")
        lines.append("lpf_freq = 2500  # Cutoff for highs")
        lines.append("")
        lines.append("# Create mids-only version")
        lines.append("incoming_mids_only = incoming |>")
        lines.append("    filter.iir.butterworth.high_pass(frequency=hpf_freq) |>")
        lines.append("    filter.iir.butterworth.low_pass(frequency=lpf_freq)")
        lines.append("")
        
        return lines
    
    def get_bass_cut_percentage(self) -> str:
        """Return human-readable bass cut percentage"""
        # This is a simplified model - actual frequency response varies with filter order
        return f"{self.cut_intensity * 100:.0f}%"


class BassCutAnalyzer:
    """
    Analyzes track content to decide bass cutting strategy
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def should_apply_bass_cut(
        self,
        incoming_bass_energy: float,
        outgoing_bass_energy: float,
        incoming_kick_strength: float,
    ) -> bool:
        """
        Decide if bass cut should be applied based on spectral content
        
        Args:
            incoming_bass_energy: 0-1 scale, bass content of incoming track
            outgoing_bass_energy: 0-1 scale, bass content of outgoing track
            incoming_kick_strength: 0-1 scale, strength of incoming kick
        
        Returns:
            True if bass cut should be applied
        """
        # Skip bass cut if incoming has very weak bass
        if incoming_bass_energy < 0.2:
            self.logger.debug("Incoming track has weak bass - skipping cut")
            return False
        
        # Skip if outgoing has no bass
        if outgoing_bass_energy < 0.1:
            self.logger.debug("Outgoing track has no bass - skipping cut")
            return False
        
        # Apply cut if both tracks have significant bass
        return True
    
    def recommend_cut_intensity(
        self,
        incoming_bass_energy: float,
        outgoing_bass_energy: float,
    ) -> float:
        """
        Recommend bass cut intensity based on relative bass levels
        
        Args:
            incoming_bass_energy: 0-1 scale
            outgoing_bass_energy: 0-1 scale
        
        Returns:
            Cut intensity 0-1 (0.50-0.80 typical range)
        """
        # If incoming bass is much stronger, cut more aggressively
        bass_ratio = incoming_bass_energy / (outgoing_bass_energy + 0.01)
        
        if bass_ratio > 1.5:
            # Incoming bass is much stronger - cut more
            cut_intensity = 0.75
        elif bass_ratio > 1.0:
            # Incoming bass slightly stronger - moderate cut
            cut_intensity = 0.65
        else:
            # Outgoing bass is stronger - light cut for incoming
            cut_intensity = 0.55
        
        # Clamp to professional range
        cut_intensity = max(0.50, min(0.80, cut_intensity))
        
        return cut_intensity


# ============================================================================
# Integration Helper
# ============================================================================

def enhance_transition_with_bass_cut(
    transition_dict: dict,
    spectral_data_incoming: dict,
    spectral_data_outgoing: dict,
    enable_bass_cut: bool = True,
) -> dict:
    """
    Enhance a transition with bass cut specifications
    
    Args:
        transition_dict: Existing transition plan
        spectral_data_incoming: Spectral analysis of incoming track
        spectral_data_outgoing: Spectral analysis of outgoing track
        enable_bass_cut: Master switch
    
    Returns:
        Enhanced transition dict with bass cut fields
    """
    if not enable_bass_cut:
        return transition_dict
    
    # Extract spectral data
    incoming_bass = spectral_data_incoming.get('bass_energy', 0.5)
    outgoing_bass = spectral_data_outgoing.get('bass_energy', 0.5)
    incoming_kick = spectral_data_incoming.get('kick_strength', 0.5)
    
    # Analyze and decide
    analyzer = BassCutAnalyzer()
    should_cut = analyzer.should_apply_bass_cut(incoming_bass, outgoing_bass, incoming_kick)
    cut_intensity = analyzer.recommend_cut_intensity(incoming_bass, outgoing_bass)
    
    # Create bass cut spec
    engine = BassCutEngine()
    trans_start = transition_dict.get('phase1_transition_start_seconds', 0)
    trans_duration = transition_dict.get('phase1_transition_bars', 16)
    bpm = transition_dict.get('bpm', 128)
    
    bass_cut_params = engine.create_bass_cut_spec(
        transition_start=trans_start,
        transition_duration_bars=trans_duration,
        bpm=bpm,
        cut_intensity=cut_intensity,
    )
    
    # Update transition
    enhanced = transition_dict.copy()
    enhanced['phase2_bass_cut_enabled'] = should_cut
    enhanced['phase2_hpf_frequency'] = bass_cut_params.hpf_frequency
    enhanced['phase2_cut_intensity'] = cut_intensity
    enhanced['phase2_strategy'] = bass_cut_params.strategy.value
    enhanced['phase2_unmask_delay_bars'] = bass_cut_params.unmask_delay_bars
    enhanced['phase2_incoming_bass_energy'] = incoming_bass
    enhanced['phase2_outgoing_bass_energy'] = outgoing_bass
    
    return enhanced


# ============================================================================
# Test/Demo
# ============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("PHASE 2: BASS CUT CONTROL - EXAMPLES")
    print("=" * 70)
    
    engine = BassCutEngine()
    analyzer = BassCutAnalyzer()
    
    # Example 1: Standard house transition
    print("\n📊 Example 1: House Track Transition (128 BPM)")
    print("-" * 70)
    
    params = engine.create_bass_cut_spec(
        transition_start=180.0,
        transition_duration_bars=16,
        bpm=128,
        cut_intensity=0.65,
        hpf_frequency=200.0,
    )
    
    is_valid, error = params.validate()
    print(f"Valid: {is_valid}")
    print(f"HPF Frequency: {params.hpf_frequency} Hz")
    print(f"Cut Intensity: {params.cut_intensity:.0%}")
    print(f"Transition Duration: {params.get_transition_duration_seconds():.2f}s ({params.transition_duration_bars} bars)")
    print(f"Unmask Starts: {params.get_unmask_start_seconds():.2f}s after transition begins")
    print(f"Unmask Duration: {params.get_unmask_duration_seconds():.2f}s")
    
    # Generate Liquidsoap code
    script = engine.generate_liquidsoap_filter(params)
    print("\nLiquidsoap Filter Code:")
    for line in script:
        print(f"  {line}")
    
    # Example 2: Analyze spectral data and recommend cut
    print("\n📊 Example 2: Spectral Analysis Based Recommendation")
    print("-" * 70)
    
    incoming_spectral = {
        'bass_energy': 0.75,  # Strong bass
        'kick_strength': 0.8,
    }
    outgoing_spectral = {
        'bass_energy': 0.70,  # Similar strength
    }
    
    should_cut = analyzer.should_apply_bass_cut(0.75, 0.70, 0.8)
    recommended_cut = analyzer.recommend_cut_intensity(0.75, 0.70)
    
    print(f"Incoming bass energy: {incoming_spectral['bass_energy']:.0%}")
    print(f"Outgoing bass energy: {outgoing_spectral['bass_energy']:.0%}")
    print(f"Should apply cut: {should_cut}")
    print(f"Recommended cut intensity: {recommended_cut:.0%}")
    
    # Example 3: Weak bassline scenario
    print("\n📊 Example 3: Weak Bassline Scenario")
    print("-" * 70)
    
    should_cut = analyzer.should_apply_bass_cut(0.15, 0.70, 0.5)
    print(f"Incoming bass energy: 15% (weak)")
    print(f"Outgoing bass energy: 70%")
    print(f"Should apply cut: {should_cut} (skipped - weak incoming bass)")
    
    # Example 4: Different strategies
    print("\n📊 Example 4: Strategy Comparison")
    print("-" * 70)
    
    strategies = [
        (BassCutStrategy.INSTANT, "Full HPF instantly, unmask over bars"),
        (BassCutStrategy.GRADUAL, "Gradually apply HPF, then unmask"),
        (BassCutStrategy.CREATIVE, "Mids-only phase before drop"),
    ]
    
    for strategy, description in strategies:
        params = engine.create_bass_cut_spec(
            transition_start=180.0,
            transition_duration_bars=16,
            bpm=128,
            strategy=strategy,
        )
        print(f"\n  {strategy.value.upper()}")
        print(f"    {description}")
