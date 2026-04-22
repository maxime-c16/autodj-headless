"""
Phase 1: Early Transitions Implementation

Implements professional DJ behavior: Start mixing incoming track 16+ bars before 
the outgoing track's outro ends, rather than waiting for the track to finish.

Current behavior: Playlist mode - queue next track when current finishes
Target behavior: DJ mode - seamlessly blend incoming while outgoing is still playing

Key Parameters:
- Transition start: outro_start_seconds - (16 bars in seconds)
- Transition duration: 16-32 bars of overlap
- Integration point: playlist.py transition generation

This module enhances the existing TransitionPlan class with early transition timing.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class TransitionTiming(Enum):
    """Timing strategies for professional DJ transitions"""
    EARLY_START = "early_start"      # Start 16+ bars before outro (DJ behavior)
    PHRASE_ALIGNED = "phrase_aligned"  # Sync with phrase boundary (beat-matched)
    DYNAMIC = "dynamic"                # Vary timing based on track content


@dataclass
class EarlyTransitionParams:
    """Parameters for early transition calculation"""
    outro_start_seconds: float        # Where outro begins in outgoing track
    bpm: float                        # Beats per minute of outgoing track
    bars_before_outro: int = 16       # How many bars before outro to start (8, 16, or 32)
    transition_duration_bars: int = 16  # Length of mixing overlap
    enable_early_start: bool = True   # Master switch
    
    def calculate_transition_start(self) -> float:
        """Calculate when to start mixing incoming track
        
        Returns:
            Float seconds from track start when mixing should begin
        """
        if not self.enable_early_start:
            # Fallback to current behavior (transition at outro)
            return self.outro_start_seconds
        
        # Convert bars to seconds: (bars * 60) / bpm
        bars_to_seconds = (self.bars_before_outro * 60.0) / self.bpm
        transition_start = self.outro_start_seconds - bars_to_seconds
        
        # Clamp to valid range (not before track start, not after outro)
        transition_start = max(0, min(transition_start, self.outro_start_seconds))
        
        return transition_start
    
    def calculate_transition_end(self) -> float:
        """Calculate when transition mixing should be complete
        
        Returns:
            Float seconds from track start when outgoing track is fully faded out
        """
        transition_duration_sec = (self.transition_duration_bars * 60.0) / self.bpm
        return self.calculate_transition_start() + transition_duration_sec


class EarlyTransitionCalculator:
    """
    Calculates early transition timings for DJ-like mixing
    
    Usage:
        calc = EarlyTransitionCalculator()
        transition_start = calc.calculate_early_transition(
            outro_start=120.5,
            bpm=128,
            bars=16
        )
    """
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
    
    def calculate_early_transition(
        self,
        outro_start: float,
        bpm: float,
        bars: int = 16,
    ) -> Tuple[float, float]:
        """
        Calculate early transition timing
        
        Args:
            outro_start: When outro begins in seconds
            bpm: BPM of the track
            bars: Bars before outro to start mixing (8, 16, or 32)
        
        Returns:
            Tuple of (transition_start_seconds, transition_end_seconds)
        
        Example:
            # For a 128 BPM track with outro at 240s
            start, end = calc.calculate_early_transition(240, 128, 16)
            # Returns: (240 - 60, 240 - 60 + 60) = (180, 240)
            # Mixing starts at 180s, completes at 240s (at outro boundary)
        """
        params = EarlyTransitionParams(
            outro_start_seconds=outro_start,
            bpm=bpm,
            bars_before_outro=bars,
            transition_duration_bars=bars,  # Same length as pre-outro window
        )
        
        start = params.calculate_transition_start()
        end = params.calculate_transition_end()
        
        self.logger.debug(
            f"Early transition: {outro_start}s outro → start at {start:.2f}s, "
            f"end at {end:.2f}s ({bars} bars at {bpm} BPM)"
        )
        
        return start, end
    
    def validate_timing(
        self,
        transition_start: float,
        transition_end: float,
        track_duration: float,
        outro_start: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that transition timing is musically sensible
        
        Args:
            transition_start: Proposed transition start
            transition_end: Proposed transition end
            track_duration: Total duration of outgoing track
            outro_start: Outro boundary
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []
        
        # Check 1: Transition doesn't start before track begins
        if transition_start < 0:
            errors.append("Transition start is before track start")
        
        # Check 2: Transition ends after outro starts
        if transition_end > track_duration:
            errors.append("Transition extends past track end")
        
        # Check 3: Transition end is at or after outro start
        if transition_end < outro_start:
            errors.append("Transition ends before outro begins")
        
        # Check 4: Minimum 4 bars of transition
        if transition_end - transition_start < 2.0:  # ~2 seconds = 4 bars at 120 BPM
            errors.append("Transition too short (minimum 4 bars)")
        
        is_valid = len(errors) == 0
        error_msg = "; ".join(errors) if errors else None
        
        return is_valid, error_msg


# ============================================================================
# Integration with existing TransitionPlan
# ============================================================================

def enhance_transition_plan_with_early_timing(
    transition_plan_dict: dict,
    spectral_data: dict,
    enable_early_start: bool = True,
) -> dict:
    """
    Enhance an existing transition plan with early start timings
    
    Args:
        transition_plan_dict: Existing TransitionPlan as dict
        spectral_data: Spectral analysis data for the outgoing track
        enable_early_start: Whether to apply early start behavior
    
    Returns:
        Enhanced transition_plan_dict with new timing fields
    """
    if not enable_early_start:
        return transition_plan_dict
    
    # Extract relevant data
    bpm = transition_plan_dict.get('bpm')
    outro_start = spectral_data.get('outro_start_seconds')
    track_duration = spectral_data.get('duration_seconds')
    
    if not (bpm and outro_start and track_duration):
        logger.warning("Missing data for early transition calculation")
        return transition_plan_dict
    
    # Calculate early transition
    calc = EarlyTransitionCalculator()
    trans_start, trans_end = calc.calculate_early_transition(
        outro_start=outro_start,
        bpm=bpm,
        bars=16,
    )
    
    # Validate
    is_valid, error_msg = calc.validate_timing(
        trans_start, trans_end, track_duration, outro_start
    )
    
    if not is_valid:
        logger.warning(f"Transition timing validation failed: {error_msg}")
        # Fall back to current behavior
        trans_start = outro_start
        trans_end = track_duration
    
    # Update transition plan
    enhanced = transition_plan_dict.copy()
    enhanced['phase1_early_start_enabled'] = True
    enhanced['phase1_transition_start_seconds'] = trans_start
    enhanced['phase1_transition_end_seconds'] = trans_end
    enhanced['phase1_transition_bars'] = 16
    enhanced['phase1_transition_timing'] = TransitionTiming.EARLY_START.value
    
    return enhanced


# ============================================================================
# Test/Demo
# ============================================================================

if __name__ == "__main__":
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    # Example 1: Calculate early transition for 128 BPM track
    calc = EarlyTransitionCalculator()
    
    print("=" * 60)
    print("PHASE 1: EARLY TRANSITIONS - EXAMPLE CALCULATIONS")
    print("=" * 60)
    
    # Scenario 1: Typical electronic music track
    print("\n📊 Scenario 1: House Track (128 BPM, 3:50 duration)")
    print("-" * 60)
    outro_start = 230  # Outro starts at 3:50
    bpm = 128
    start, end = calc.calculate_early_transition(outro_start, bpm, 16)
    print(f"Outro start:        {outro_start}s")
    print(f"Track BPM:          {bpm}")
    print(f"Transition start:   {start:.1f}s ({outro_start - start:.1f}s before outro)")
    print(f"Transition end:     {end:.1f}s")
    print(f"Mixing duration:    {end - start:.1f}s ({int((end-start)/(60/bpm))} bars)")
    
    # Scenario 2: Faster track
    print("\n📊 Scenario 2: Techno Track (135 BPM, 4:00 duration)")
    print("-" * 60)
    outro_start = 240
    bpm = 135
    start, end = calc.calculate_early_transition(outro_start, bpm, 16)
    print(f"Outro start:        {outro_start}s")
    print(f"Track BPM:          {bpm}")
    print(f"Transition start:   {start:.1f}s ({outro_start - start:.1f}s before outro)")
    print(f"Transition end:     {end:.1f}s")
    print(f"Mixing duration:    {end - start:.1f}s ({int((end-start)/(60/bpm))} bars)")
    
    # Scenario 3: Slower track
    print("\n📊 Scenario 3: Deep House Track (100 BPM, 5:30 duration)")
    print("-" * 60)
    outro_start = 320
    bpm = 100
    start, end = calc.calculate_early_transition(outro_start, bpm, 16)
    print(f"Outro start:        {outro_start}s")
    print(f"Track BPM:          {bpm}")
    print(f"Transition start:   {start:.1f}s ({outro_start - start:.1f}s before outro)")
    print(f"Transition end:     {end:.1f}s")
    print(f"Mixing duration:    {end - start:.1f}s ({int((end-start)/(60/bpm))} bars)")
    
    # Validation example
    print("\n" + "=" * 60)
    print("VALIDATION EXAMPLES")
    print("=" * 60)
    
    print("\n✅ Valid Transition:")
    is_valid, error = calc.validate_timing(180, 240, 250, 230)
    print(f"Valid: {is_valid}, Error: {error}")
    
    print("\n❌ Invalid Transition (starts before outro):")
    is_valid, error = calc.validate_timing(240, 300, 350, 230)
    print(f"Valid: {is_valid}, Error: {error}")
    
    print("\n❌ Invalid Transition (too short):")
    is_valid, error = calc.validate_timing(238, 240, 350, 230)
    print(f"Valid: {is_valid}, Error: {error}")
