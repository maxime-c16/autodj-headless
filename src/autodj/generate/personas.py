"""
DJ Persona System - Maps selector modes to mixing styles and Phase 5 techniques

Based on professional DJ research from Pioneer DJ, Beatmatch community,
and analysis of genres: Tech House, Hard Techno, Minimal Techno, Melodic Techno, Acid Techno
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional
from ..render.phase5_micro_techniques import MicroTechniqueType


class DJPersona(Enum):
    """DJ Persona types matching selector modes and mixing styles"""
    TECH_HOUSE = "tech_house"          # MerlinGreedySelector - Balanced
    HIGH_ENERGY = "high_energy"        # BlastxcssSelector - Energy curve
    MINIMAL = "minimal"                # New - Minimal Techno style
    ACID = "acid"                      # New - Acid Techno style


@dataclass
class PersonaConfig:
    """Configuration for a DJ persona"""
    name: str                          # Display name
    selector_mode: str                 # "merlin" or "blastxcss"
    description: str                   # Short description
    bpm_range: tuple                   # (min, max) BPM
    playlist_title_templates: List[str]  # Title generation patterns
    
    # Phase 5: Micro-technique selection
    technique_frequency: float         # 1.0 = every track, 0.3 = 30% of transitions
    technique_count_per_section: int   # How many techniques per technique occurrence
    min_technique_interval_bars: int   # Minimum bars between techniques
    max_technique_interval_bars: int   # Maximum bars between techniques
    
    # Preferred techniques (in priority order)
    preferred_techniques: List[MicroTechniqueType]
    
    # Avoided techniques
    avoid_techniques: List[MicroTechniqueType]
    
    # Technique duration multiplier (1.0 = normal, 0.5 = shorter, 1.5 = longer)
    technique_duration_multiplier: float
    
    # Energy curve preference
    energy_build: str                  # "gradual", "aggressive", "minimal", "dynamic"


# ============================================================================
# PERSONA DEFINITIONS - Based on Professional DJ Research
# ============================================================================

TECH_HOUSE_PERSONA = PersonaConfig(
    name="Tech House Energy",
    selector_mode="merlin",
    description="Tech House: Quick cuts, stutter rolls, vocal loops. Balanced energy with frequent effects.",
    bpm_range=(125, 135),
    playlist_title_templates=[
        "Tech House Grooves",
        "Peak Energy Cuts",
        "Stutter & Sweep",
        "Vocal Texture Mix",
        "Four-on-the-Floor Energy",
    ],
    technique_frequency=0.75,          # 75% of transitions get techniques
    technique_count_per_section=2,     # 2 techniques per occurrence
    min_technique_interval_bars=8,     # Every 8-16 bars minimum
    max_technique_interval_bars=16,
    preferred_techniques=[
        MicroTechniqueType.STUTTER_ROLL,      # Short loops (1-2 bars) - tech house staple
        MicroTechniqueType.ECHO_OUT_RETURN,   # Vocal echo-outs - prominent in tech house
        MicroTechniqueType.QUICK_CUT_REVERB,  # Quick cuts at phrase changes
        MicroTechniqueType.BASS_CUT_ROLL,     # Bass control for transitions
        MicroTechniqueType.FILTER_SWEEP,      # 4-8 bar sweeps for building
    ],
    avoid_techniques=[
        MicroTechniqueType.REVERB_TAIL_CUT,   # Less common in tech house
        MicroTechniqueType.PING_PONG_PAN,     # Too spacey for tech house groove
    ],
    technique_duration_multiplier=0.9,  # Slightly shorter than default
    energy_build="gradual",
)


HIGH_ENERGY_PERSONA = PersonaConfig(
    name="Hard Techno Assault",
    selector_mode="blastxcss",
    description="Hard Techno: Aggressive drops, relentless bass cuts, rapid stutters. Peak energy at midpoint.",
    bpm_range=(160, 165),
    playlist_title_templates=[
        "Hard Techno Assault",
        "Relentless Drops",
        "Bass Cut Madness",
        "Peak Energy Rush",
        "Industrial Grooves",
    ],
    technique_frequency=0.95,          # 95% of transitions - heavy FX usage
    technique_count_per_section=3,     # 3 techniques per occurrence
    min_technique_interval_bars=5,     # Every 5-12 bars (more frequent)
    max_technique_interval_bars=12,
    preferred_techniques=[
        MicroTechniqueType.BASS_CUT_ROLL,          # Core hard techno technique
        MicroTechniqueType.STUTTER_ROLL,           # Aggressive loops
        MicroTechniqueType.QUICK_CUT_REVERB,       # Punctuate drops
        MicroTechniqueType.FILTER_SWEEP,           # Aggressive sweeps
        MicroTechniqueType.LOOP_STUTTER_ACCEL,     # 4→2→1 progression for tension
    ],
    avoid_techniques=[
        MicroTechniqueType.REVERB_TAIL_CUT,        # Too ambient
        MicroTechniqueType.PING_PONG_PAN,          # Too subtle
        MicroTechniqueType.MUTE_DIM,               # Not aggressive enough
    ],
    technique_duration_multiplier=1.1,  # Longer, more pronounced effects
    energy_build="aggressive",
)


MINIMAL_PERSONA = PersonaConfig(
    name="Minimal Hypnotic",
    selector_mode="merlin",
    description="Minimal Techno: Sparse production, long sweeps, hypnotic repetition. Ricardo Villalobos style.",
    bpm_range=(120, 130),
    playlist_title_templates=[
        "Minimal Hypnosis",
        "Sparse Grooves",
        "Deep Meditation",
        "Subtle Tension Build",
        "Minimalist Journey",
    ],
    technique_frequency=0.30,          # 30% of transitions - very sparse
    technique_count_per_section=1,     # 1 technique per occurrence
    min_technique_interval_bars=16,    # Every 16-32+ bars (very infrequent)
    max_technique_interval_bars=32,
    preferred_techniques=[
        MicroTechniqueType.FILTER_SWEEP,           # Long 8-16 bar sweeps for tension building
        MicroTechniqueType.MUTE_DIM,               # Brief silence/dimming for breathing room
        MicroTechniqueType.REVERB_TAIL_CUT,        # Space sensation
        MicroTechniqueType.HIGH_MID_BOOST,         # Subtle clarity on drums
    ],
    avoid_techniques=[
        MicroTechniqueType.STUTTER_ROLL,           # Too intrusive for minimal
        MicroTechniqueType.BASS_CUT_ROLL,          # Too aggressive
        MicroTechniqueType.QUICK_CUT_REVERB,       # Disrupts hypnotic state
        MicroTechniqueType.LOOP_STUTTER_ACCEL,     # Too dynamic
        MicroTechniqueType.PING_PONG_PAN,          # Breaks minimalism
    ],
    technique_duration_multiplier=1.3,  # Longer, drawn-out effects
    energy_build="minimal",
)


ACID_PERSONA = PersonaConfig(
    name="Acid Squelch",
    selector_mode="merlin",
    description="Acid Techno: Squelchy TB-303 lines, build-release arcs, vintage aggression.",
    bpm_range=(130, 140),
    playlist_title_templates=[
        "Acid Squelch Journey",
        "303 Dream State",
        "Acidic Breakdown",
        "Vintage Aggression",
        "Squelch & Release",
    ],
    technique_frequency=0.65,          # 65% of transitions
    technique_count_per_section=2,     # 2 techniques per occurrence
    min_technique_interval_bars=6,     # Every 6-10 bars
    max_technique_interval_bars=10,
    preferred_techniques=[
        MicroTechniqueType.BASS_CUT_ROLL,          # Remove/return bass for tension
        MicroTechniqueType.ECHO_OUT_RETURN,        # Echo out acid leads (characteristic)
        MicroTechniqueType.LOOP_STUTTER_ACCEL,     # 4→2→1 progression on acid riffs
        MicroTechniqueType.STUTTER_ROLL,           # Loops on acid sequences
        MicroTechniqueType.PING_PONG_PAN,          # Spatial movement of acid lines
    ],
    avoid_techniques=[
        MicroTechniqueType.MUTE_DIM,               # Breaks the acid continuity
        MicroTechniqueType.REVERB_TAIL_CUT,        # Acid already has space
    ],
    technique_duration_multiplier=1.0,  # Standard duration
    energy_build="dynamic",
)


# ============================================================================
# PERSONA LOOKUP & UTILITIES
# ============================================================================

PERSONA_CONFIGS: Dict[DJPersona, PersonaConfig] = {
    DJPersona.TECH_HOUSE: TECH_HOUSE_PERSONA,
    DJPersona.HIGH_ENERGY: HIGH_ENERGY_PERSONA,
    DJPersona.MINIMAL: MINIMAL_PERSONA,
    DJPersona.ACID: ACID_PERSONA,
}


def get_persona_config(persona: DJPersona) -> PersonaConfig:
    """Get configuration for a persona"""
    return PERSONA_CONFIGS[persona]


def get_persona_by_name(name: str) -> Optional[DJPersona]:
    """Lookup persona by name string"""
    name_lower = name.lower()
    for persona in DJPersona:
        if persona.value == name_lower:
            return persona
    return None


def list_personas() -> List[DJPersona]:
    """List all available personas"""
    return list(DJPersona)
