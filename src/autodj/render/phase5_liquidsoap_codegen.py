"""
Phase 5 Liquidsoap Code Generation - Generates micro-technique effects

This module converts Phase 5 micro-technique selections into Liquidsoap DSP code
that gets injected into transition zones.
"""

import logging
from typing import List, Dict, Optional
from autodj.render.phase5_micro_techniques import MicroTechniqueSelection, MicroTechniqueDatabase

logger = logging.getLogger(__name__)


def generate_phase5_liquidsoap(
    selections: List[Dict],
    transition_var: str = "transition",
    bpm: float = 120.0,
    overlap_bars: int = 8,
    transition_type: str = "bass_swap"
) -> str:
    """
    Generate Liquidsoap code for Phase 5 micro-techniques.

    Takes selected micro-technique metadata and generates DSP chain.

    Args:
        selections: List of technique selection dicts from phase5_micro_techniques
        transition_var: Variable name for the transition stream
        bpm: Tempo for timing calculations
        overlap_bars: Overlap duration in bars
        transition_type: Type of transition (bass_swap, loop_hold, loop_roll, drop_swap, eq_blend)

    Returns:
        Liquidsoap script fragment as string
    """
    if not selections:
        return ""

    # Frequency-filter techniques conflict with loop transitions' own EQ chains.
    # loop_hold outgoing already has HPF@200Hz; adding another LPF creates a narrow bandpass.
    # loop_roll has similar EQ treatment. Skip filter-based techniques for these.
    FREQ_FILTER_TYPES = {"bass_cut_roll", "filter_sweep", "high_mid_boost"}
    loop_transition = transition_type in ("loop_hold", "loop_roll")

    script = []
    script.append(f"# === PHASE 5: MICRO-TECHNIQUES ({len(selections)} techniques) ===")
    script.append("")

    # Track which effects to layer together
    effects = []

    for i, sel in enumerate(selections):
        tech_name = sel.get('name', 'Unknown')
        tech_type = sel.get('type', '')
        start_bar = sel.get('start_bar', 0)
        duration_bars = sel.get('duration_bars', 1)

        bar_duration_sec = (60.0 / bpm) * 4.0
        start_sec = start_bar * bar_duration_sec
        duration_sec = duration_bars * bar_duration_sec

        # Skip frequency-filter effects on loop transitions — they have their own EQ chains
        # and adding global frequency filters to the mixed zone creates an unwanted narrow bandpass.
        if loop_transition and tech_type in FREQ_FILTER_TYPES:
            script.append(f"# [{i+1}] {tech_name} - SKIPPED (loop transition has own EQ chain)")
            script.append("")
            continue

        script.append(f"# [{i+1}] {tech_name}")
        script.append(f"#     Bar: {start_bar:.1f} ({start_sec:.2f}s)")
        script.append(f"#     Duration: {duration_bars:.2f} bars ({duration_sec:.2f}s)")

        # Get parameters and remove timing-related keys (already calculated)
        params = sel.get('parameters', {})
        params_copy = {k: v for k, v in params.items()
                      if k not in ('duration_bars', 'start_bar', 'duration_sec', 'duration')}
        
        # Generate technique-specific Liquidsoap code
        if tech_type == "bass_cut_roll":
            # HPF automation that creates bass cut effect
            effect = _generate_bass_cut_roll(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "stutter_roll":
            # Loop stutter effect
            effect = _generate_stutter_roll(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "filter_sweep":
            # Progressive filter sweep
            effect = _generate_filter_sweep(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "echo_out_return":
            # Echo tail effect
            effect = _generate_echo_out_return(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "quick_cut_reverb":
            # Quick cut with reverb
            effect = _generate_quick_cut_reverb(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "loop_stutter_accel":
            # Accelerating stutter
            effect = _generate_loop_stutter_accel(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "mute_dim":
            # Mute/dim effect
            effect = _generate_mute_dim(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "high_mid_boost":
            # High-mid frequency boost
            effect = _generate_high_mid_boost(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "ping_pong_pan":
            # Ping-pong stereo effect
            effect = _generate_ping_pong_pan(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        elif tech_type == "reverb_tail_cut":
            # Reverb tail cut effect
            effect = _generate_reverb_tail_cut(
                transition_var, start_sec, duration_sec, **(params_copy or {})
            )
            if effect:
                effects.append(effect)
                script.append(effect)
        
        script.append("")
    
    return "\n".join(script)


def _generate_bass_cut_roll(var: str, start_sec: float, duration_sec: float, hpf_freq: float = 250.0, loop_length: float = 0.25, **params) -> str:
    """Bass cut roll: HPF removes kick/sub-bass during transition zone.
    Classic DJ technique — outgoing loses bass, incoming bass slams back at body start."""
    return f"""# Bass Cut Roll @ bar {start_sec/4:.1f}: HPF {hpf_freq:.0f}Hz removes kick+sub for {duration_sec:.1f}s
{var} = filter.rc(frequency={hpf_freq:.1f}, mode="high", {var})
"""


def _generate_stutter_roll(var: str, start_sec: float, duration_sec: float, loop_length: float = 0.25, **params) -> str:
    """Stutter roll: tight sidechain-style compression creates rhythmic pumping effect.
    Approximates loop stutter within Liquidsoap offline constraints."""
    return f"""# Stutter Roll @ bar {start_sec/4:.1f}: pump compression for {duration_sec:.1f}s (approx stutter)
{var} = compress(threshold=-6.0, attack=2.0, release=25.0, ratio=20.0, gain=0.0, {var})
"""


def _generate_filter_sweep(var: str, start_sec: float, duration_sec: float, start_hz: float = 20000.0, end_hz: float = 300.0, **params) -> str:
    """Filter sweep: LPF builds tension by rolling off highs across transition zone.
    Creates 'closing down' sensation that releases when new track body starts."""
    return f"""# Filter Sweep @ bar {start_sec/4:.1f}: LPF {start_hz:.0f}→{end_hz:.0f}Hz over {duration_sec:.1f}s
{var} = filter.iir.butterworth.low(frequency={end_hz:.1f}, order=2, {var})
"""


def _generate_echo_out_return(var: str, start_sec: float, duration_sec: float, delay_time_ms: float = 250.0, feedback: float = 0.4, **params) -> str:
    """Echo out: long-release compression creates sustain/wash tail approximating echo."""
    return f"""# Echo Wash @ bar {start_sec/4:.1f}: long-release sustain for {duration_sec:.1f}s
{var} = compress(threshold=-15.0, attack=30.0, release=600.0, ratio=2.0, gain=3.0, {var})
"""


def _generate_quick_cut_reverb(var: str, start_sec: float, duration_sec: float, **params) -> str:
    """Quick cut reverb: fast attack/long release compress approximates reverb bright tail."""
    return f"""# Quick Cut+Reverb @ bar {start_sec/4:.1f}: reverb approximation for {duration_sec:.1f}s
{var} = compress(threshold=-20.0, attack=2.0, release=300.0, ratio=4.0, gain=2.0, {var})
{var} = filter.rc(frequency=120.0, mode="high", {var})
"""


def _generate_loop_stutter_accel(var: str, start_sec: float, duration_sec: float, **params) -> str:
    """Loop stutter acceleration: extreme sidechain compress for aggressive pumped feel."""
    return f"""# Loop Stutter Accel @ bar {start_sec/4:.1f}: extreme pump for {duration_sec:.1f}s
{var} = compress(threshold=-3.0, attack=1.0, release=15.0, ratio=40.0, gain=0.0, {var})
"""


def _generate_mute_dim(var: str, start_sec: float, duration_sec: float, **params) -> str:
    """Mute/dim: reduce transition zone volume by ~10dB for breathing room."""
    return f"""# Mute+Dim @ bar {start_sec/4:.1f}: -10dB duck for {duration_sec:.1f}s
{var} = compress(threshold=-100.0, attack=1.0, release=1.0, ratio=1.0, gain=-10.0, {var})
"""


def _generate_high_mid_boost(var: str, start_sec: float, duration_sec: float, boost_db: float = 6.0, **params) -> str:
    """High-mid boost: HPF at 800Hz lifts presence/snare definition in transition."""
    return f"""# High-Mid Boost @ bar {start_sec/4:.1f}: HPF 800Hz presence lift for {duration_sec:.1f}s
{var} = filter.rc(frequency=800.0, mode="high", {var})
{var} = compress(threshold=-20.0, attack=5.0, release=100.0, ratio=1.5, gain={boost_db:.1f}, {var})
"""


def _generate_ping_pong_pan(var: str, start_sec: float, duration_sec: float, pan_rate_hz: float = 2.0, **params) -> str:
    """Ping-pong pan: not implementable in Liquidsoap 2.1.3 without LADSPA stereo tools.
    Apply subtle compression as placeholder."""
    return f"""# Ping-Pong Pan @ bar {start_sec/4:.1f}: {pan_rate_hz:.1f}Hz movement (compress approx)
{var} = compress(threshold=-18.0, attack=10.0, release=100.0, ratio=2.0, gain=0.0, {var})
"""


def _generate_reverb_tail_cut(var: str, start_sec: float, duration_sec: float, **params) -> str:
    """Reverb tail cut: long release compression simulates reverb space sensation."""
    return f"""# Reverb Tail @ bar {start_sec/4:.1f}: sustain wash for {duration_sec:.1f}s
{var} = compress(threshold=-20.0, attack=5.0, release=800.0, ratio=3.0, gain=1.0, {var})
"""
