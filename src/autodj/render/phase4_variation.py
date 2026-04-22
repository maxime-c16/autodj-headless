"""
Phase 4: Dynamic Variation Implementation

Randomizes DJ transition techniques to avoid repetitive automation patterns.
Makes the mix sound more natural and less "algorithmic".

Strategy:
- 60% of transitions: Gradual EQ adjustments (8-16 bar sweep)
- 40% of transitions: Instant/quick bass swaps (4 bar or less)
- Vary timing ±2 bars around phrase boundary
- Vary cut intensities (50-80% range, not fixed value)
- Occasionally skip bass cut on weak-bassline tracks
"""

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class TransitionStrategy(Enum):
    """Available transition application strategies"""
    GRADUAL = "gradual"      # Smooth EQ adjustments over 8-16 bars (natural)
    INSTANT = "instant"      # Quick bass swap, ~4 bars (energetic)
    CREATIVE = "creative"    # Mids-only before drop (advanced)
    BALANCED = "balanced"    # Mix of above (compromise)


@dataclass
class VariationParams:
    """Parameters for dynamic variation"""
    # Probability settings (0-1 scale)
    gradual_probability: float = 0.60      # 60% of transitions
    instant_probability: float = 0.40      # 40% of transitions
    
    # Timing variation (±bars)
    timing_jitter_bars: float = 2.0        # ±2 bars variation
    
    # Intensity variation (0-1 scale)
    intensity_min: float = 0.50
    intensity_max: float = 0.80
    intensity_variance: float = 0.10       # How much to vary (standard dev)
    
    # Bass cut skipping
    skip_bass_cut_probability: float = 0.05  # 5% chance to skip
    weak_bassline_threshold: float = 0.25    # Below this = weak
    
    # Seed for reproducibility (None = random)
    seed: Optional[int] = None
    
    def __post_init__(self):
        """Validate parameters"""
        assert 0 <= self.gradual_probability <= 1.0
        assert 0 <= self.instant_probability <= 1.0
        assert abs((self.gradual_probability + self.instant_probability) - 1.0) < 0.01, \
            "Probabilities must sum to ~1.0"
        assert self.intensity_min < self.intensity_max
        assert 0 <= self.intensity_min
        assert self.intensity_max <= 1.0


class DynamicVariationEngine:
    """
    Applies randomized variation to transitions for natural-sounding mixing
    
    Usage:
        engine = DynamicVariationEngine()
        varied_transition = engine.apply_variation(transition_dict)
    """
    
    def __init__(self, params: Optional[VariationParams] = None):
        self.params = params or VariationParams()
        self.logger = logging.getLogger(__name__)
        
        # Set random seed if specified
        if self.params.seed is not None:
            random.seed(self.params.seed)
    
    def apply_variation(self, transition: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply dynamic variation to a transition
        
        Args:
            transition: Transition dict (with Phase 1-2 fields already set)
        
        Returns:
            Enhanced transition dict with Phase 4 variation fields
        """
        # Choose strategy based on probability
        strategy = self._select_strategy()
        
        # Calculate timing variation
        timing_variation = self._calculate_timing_variation(transition)
        
        # Calculate intensity variation
        intensity_variation = self._calculate_intensity_variation(transition)
        
        # Decide whether to skip bass cut
        skip_bass_cut = self._decide_skip_bass_cut(transition)
        
        # Build enhanced transition
        enhanced = transition.copy()
        enhanced['phase4_strategy'] = strategy.value
        enhanced['phase4_timing_variation_bars'] = timing_variation
        enhanced['phase4_intensity_variation'] = intensity_variation
        enhanced['phase4_skip_bass_cut'] = skip_bass_cut
        
        # Log the variation
        self.logger.debug(
            f"Phase 4 variation: {strategy.value} | "
            f"timing: {timing_variation:+.1f} bars | "
            f"intensity: {intensity_variation:.0%} | "
            f"skip_bass_cut: {skip_bass_cut}"
        )
        
        return enhanced
    
    def _select_strategy(self) -> TransitionStrategy:
        """Select transition strategy based on probabilities"""
        rand = random.random()
        
        if rand < self.params.gradual_probability:
            return TransitionStrategy.GRADUAL
        else:
            return TransitionStrategy.INSTANT
    
    def _calculate_timing_variation(self, transition: Dict[str, Any]) -> float:
        """
        Calculate timing variation (±bars around phrase boundary)
        
        Returns:
            Float bars offset (negative = earlier, positive = later)
        """
        # Gaussian distribution centered at 0
        variation = random.gauss(0, self.params.timing_jitter_bars / 2)
        
        # Clamp to ±timing_jitter_bars
        variation = max(
            -self.params.timing_jitter_bars,
            min(self.params.timing_jitter_bars, variation)
        )
        
        return variation
    
    def _calculate_intensity_variation(self, transition: Dict[str, Any]) -> float:
        """
        Calculate bass cut intensity variation
        
        Returns:
            Float 0-1 scale intensity
        """
        # Get base intensity from Phase 2 (if present)
        base_intensity = transition.get('phase2_cut_intensity', 0.65)
        
        # Apply gaussian variation
        variance = random.gauss(0, self.params.intensity_variance)
        varied = base_intensity + variance
        
        # Clamp to valid range
        varied = max(
            self.params.intensity_min,
            min(self.params.intensity_max, varied)
        )
        
        return varied
    
    def _decide_skip_bass_cut(self, transition: Dict[str, Any]) -> bool:
        """
        Decide if bass cut should be skipped
        
        Reasons to skip:
        - Random chance (naturalness)
        - Incoming track has weak bass
        
        Returns:
            True if bass cut should be skipped
        """
        # Random chance to skip (5% default)
        if random.random() < self.params.skip_bass_cut_probability:
            self.logger.debug("Skipping bass cut: random variation")
            return True
        
        # Check incoming bass energy
        incoming_bass = transition.get('phase2_incoming_bass_energy', 0.5)
        if incoming_bass < self.params.weak_bassline_threshold:
            self.logger.debug(f"Skipping bass cut: weak incoming bass ({incoming_bass:.0%})")
            return True
        
        return False
    
    def apply_batch_variation(self, transitions: list) -> list:
        """
        Apply variation to multiple transitions
        
        Args:
            transitions: List of transition dicts
        
        Returns:
            List of varied transition dicts
        """
        return [self.apply_variation(t) for t in transitions]
    
    def get_statistics(self, transitions: list) -> Dict[str, Any]:
        """
        Calculate statistics about variation applied
        
        Args:
            transitions: List of varied transitions
        
        Returns:
            Dict with statistics
        """
        if not transitions:
            return {}
        
        gradual_count = sum(1 for t in transitions if t.get('phase4_strategy') == 'gradual')
        instant_count = sum(1 for t in transitions if t.get('phase4_strategy') == 'instant')
        skip_count = sum(1 for t in transitions if t.get('phase4_skip_bass_cut', False))
        
        timing_vars = [t.get('phase4_timing_variation_bars', 0) for t in transitions]
        intensity_vars = [t.get('phase4_intensity_variation', 0.65) for t in transitions]
        
        return {
            'total_transitions': len(transitions),
            'gradual_count': gradual_count,
            'instant_count': instant_count,
            'gradual_percentage': gradual_count / len(transitions),
            'instant_percentage': instant_count / len(transitions),
            'skip_bass_cut_count': skip_count,
            'avg_timing_variation': sum(timing_vars) / len(timing_vars),
            'avg_intensity': sum(intensity_vars) / len(intensity_vars),
            'min_intensity': min(intensity_vars),
            'max_intensity': max(intensity_vars),
        }


def enhance_transitions_with_variation(
    transitions: list,
    params: Optional[VariationParams] = None,
) -> list:
    """
    Enhance all transitions with dynamic variation
    
    Args:
        transitions: List of transition dicts
        params: Variation parameters (uses defaults if None)
    
    Returns:
        List of enhanced transitions with Phase 4 fields
    """
    engine = DynamicVariationEngine(params or VariationParams())
    varied = engine.apply_batch_variation(transitions)
    
    # Log statistics
    stats = engine.get_statistics(varied)
    logger.info(
        f"Phase 4 variation applied: {stats['gradual_count']} gradual, "
        f"{stats['instant_count']} instant, "
        f"{stats['skip_bass_cut_count']} bass cuts skipped"
    )
    
    return varied


# ============================================================================
# Test/Demo
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("PHASE 4: DYNAMIC VARIATION - EXAMPLES")
    print("=" * 70)
    
    # Create engine
    params = VariationParams(seed=42)  # Fixed seed for reproducible demo
    engine = DynamicVariationEngine(params)
    
    # Create sample transitions
    sample_transitions = [
        {
            'track_id': i,
            'bpm': 128,
            'phase1_transition_start_seconds': 180 + (i * 10),
            'phase1_transition_bars': 16,
            'phase2_cut_intensity': 0.65,
            'phase2_incoming_bass_energy': 0.75,
            'phase2_bass_cut_enabled': True,
        }
        for i in range(10)
    ]
    
    # Apply variation
    print("\n📊 Applying Phase 4 variation to 10 transitions:")
    print("-" * 70)
    
    varied = engine.apply_batch_variation(sample_transitions)
    
    for i, trans in enumerate(varied):
        print(
            f"\nTransition {i}: "
            f"Strategy={trans['phase4_strategy']}, "
            f"Timing={trans['phase4_timing_variation_bars']:+.1f} bars, "
            f"Intensity={trans['phase4_intensity_variation']:.0%}, "
            f"Skip={trans['phase4_skip_bass_cut']}"
        )
    
    # Statistics
    print("\n" + "=" * 70)
    print("STATISTICS")
    print("-" * 70)
    
    stats = engine.get_statistics(varied)
    print(f"Total transitions: {stats['total_transitions']}")
    print(f"Gradual: {stats['gradual_count']} ({stats['gradual_percentage']:.0%})")
    print(f"Instant: {stats['instant_count']} ({stats['instant_percentage']:.0%})")
    print(f"Bass cuts skipped: {stats['skip_bass_cut_count']}")
    print(f"Avg timing variation: {stats['avg_timing_variation']:+.2f} bars")
    print(f"Avg intensity: {stats['avg_intensity']:.0%} (range: {stats['min_intensity']:.0%}-{stats['max_intensity']:.0%})")
    
    # Example with different seed
    print("\n" + "=" * 70)
    print("VARIATION WITH DIFFERENT SEED (Different Random Results)")
    print("-" * 70)
    
    params2 = VariationParams(seed=123)
    engine2 = DynamicVariationEngine(params2)
    varied2 = engine2.apply_batch_variation(sample_transitions)
    
    print(f"\nFirst transition:")
    print(f"  Seed 42:  {varied[0]['phase4_strategy']} | "
          f"timing={varied[0]['phase4_timing_variation_bars']:+.1f}")
    print(f"  Seed 123: {varied2[0]['phase4_strategy']} | "
          f"timing={varied2[0]['phase4_timing_variation_bars']:+.1f}")
