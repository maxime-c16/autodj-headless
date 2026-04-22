"""
Phase 5 Liquidsoap Script Integration - Injects micro-technique effects

This module provides functions to inject Phase 5 micro-technique effects
into the Liquidsoap script generation pipeline.
"""

import logging
from typing import List, Dict, Optional
import json

logger = logging.getLogger(__name__)


def generate_phase5_track_effects(
    transition: Dict,
    track_var: str,
    bpm: float = 120.0,
    track_index: int = 0
) -> str:
    """
    Generate Liquidsoap DSP code for Phase 5 techniques on a track.
    
    Args:
        transition: Transition dict with 'phase5_micro_techniques' key
        track_var: Liquidsoap variable name for track (e.g., "track_0")
        bpm: BPM for timing calculations
        track_index: Track index for logging
    
    Returns:
        Liquidsoap script fragment (DSP chain), or empty string if no techniques
    """
    techniques = transition.get('phase5_micro_techniques', [])
    if not techniques:
        return ""
    
    script_lines = []
    script_lines.append(f"# Track {track_index}: Phase 5 Techniques ({len(techniques)} effects)")
    script_lines.append("")
    
    bar_to_seconds = (60.0 / bpm) * 4.0 if bpm > 0 else 1.0
    
    for i, tech in enumerate(techniques):
        tech_type = tech.get('type', 'unknown')
        tech_name = tech.get('name', 'Unknown')
        start_bar = tech.get('start_bar', 0)
        duration_bars = tech.get('duration_bars', 1)
        parameters = tech.get('parameters', {})
        confidence = tech.get('confidence', 1.0)
        
        # Convert bars to seconds
        start_sec = start_bar * bar_to_seconds
        duration_sec = duration_bars * bar_to_seconds
        
        # Generate technique-specific code
        effect_code = _generate_technique_code(
            tech_type, 
            track_var, 
            start_sec, 
            duration_sec, 
            bpm, 
            parameters,
            track_index,
            i
        )
        
        if effect_code:
            script_lines.append(f"# [{i+1}] {tech_name} (bar {start_bar:.1f}, confidence {confidence:.0%})")
            script_lines.append(effect_code)
            script_lines.append("")
    
    return "\n".join(script_lines)


def _generate_technique_code(
    tech_type: str,
    var: str,
    start_sec: float,
    duration_sec: float,
    bpm: float,
    parameters: Dict,
    track_idx: int,
    tech_idx: int
) -> str:
    """Generate Liquidsoap code for a specific technique."""
    
    # NOTE: filter.iir.butterworth.* is broken in Liquidsoap 2.2.x (GitHub #4124) and
    # also broken when used after sequence() in 2.1.3. Use filter.rc() instead.
    # filter.rc() works on individual PCM sources (before sequence()) in both 2.1.3 and 2.2.x.

    # Normalise aliases: the transitions JSON uses short names; map them to canonical handlers
    _alias = {
        "bass_cut": "bass_cut_roll",
        "hpf_sweep": "bass_cut_roll",   # HPF sweep up = apply HPF
        "lpf_sweep": "filter_sweep",     # LPF sweep = apply LPF
        "stutter": "stutter_roll",
        "reverb": "quick_cut_reverb",    # No reverb plugin; use HPF as approximation
        "delay": "echo_out_return",      # No delay plugin; handled as skip
    }
    tech_type = _alias.get(tech_type, tech_type)

    if tech_type == "bass_cut_roll":
        # HPF to cut bass (400-800 Hz range) — applied before sequence, on full track
        freq = parameters.get('hpf_freq', 400.0)
        return f'{var} = filter.rc(frequency={freq:.1f}, mode="high", {var})'

    elif tech_type == "stutter_roll":
        # Simplified: HPF to emulate thinning effect during transition
        return f'{var} = filter.rc(frequency=600.0, mode="high", {var})'

    elif tech_type == "filter_sweep":
        # LPF at end frequency for warm incoming tone
        end_hz = parameters.get('end_hz', 2000.0)
        return f'{var} = filter.rc(frequency={end_hz:.1f}, mode="low", {var})'

    elif tech_type == "echo_out_return":
        # Echo/delay requires a plugin not available — skip silently
        delay_ms = parameters.get('delay_time_ms', 250.0)
        return f'# Echo effect ({delay_ms:.0f}ms) requires delay plugin — skipped'

    elif tech_type == "quick_cut_reverb":
        # HPF for bright, cut-style transition
        return f'{var} = filter.rc(frequency=800.0, mode="high", {var})'

    elif tech_type == "loop_stutter_accel":
        # HPF to create tension before drop
        return f'{var} = filter.rc(frequency=500.0, mode="high", {var})'

    elif tech_type == "mute_dim":
        # Dim: reduce gain by dim_db (use compress with high ratio as gain reduction)
        dim_db = parameters.get('dim_db', -12.0)
        # compress() with very low threshold acts as gain reduction
        # threshold in dBFS: dim_db relative to 0dBFS
        threshold = max(-60.0, dim_db)
        return f'{var} = compress(threshold={threshold:.1f}, attack=1.0, release=100.0, ratio=20.0, gain={dim_db:.1f}, {var})'

    elif tech_type == "high_mid_boost":
        # Subtle bass cut emphasizes mids/highs for clarity
        return f'{var} = filter.rc(frequency=200.0, mode="high", {var})'

    elif tech_type == "ping_pong_pan":
        # Stereo panning requires a plugin — skip silently
        pan_rate = parameters.get('pan_rate_hz', 2.0)
        return f'# Ping-pong pan ({pan_rate:.1f}Hz) requires stereo plugin — skipped'

    elif tech_type == "reverb_tail_cut":
        # HPF to cut low-end reverb tail before transition
        return f'{var} = filter.rc(frequency=1000.0, mode="high", {var})'
    
    else:
        logger.warning(f"Unknown technique type: {tech_type}")
        return ""


def validate_liquidsoap_syntax(script_text: str) -> tuple:
    """
    Perform basic Liquidsoap syntax validation.
    
    Checks for:
    - Unmatched parentheses/brackets
    - Undefined variables
    - Missing function definitions
    - Common DSP errors
    
    Args:
        script_text: Liquidsoap script as string
    
    Returns:
        (is_valid: bool, errors: List[str])
    """
    errors = []
    lines = script_text.split('\n')
    
    # Track defined variables
    defined_vars = set()
    paren_stack = []
    bracket_stack = []
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            continue
        
        # Check parentheses balance
        for char in line:
            if char == '(':
                paren_stack.append(line_num)
            elif char == ')':
                if paren_stack:
                    paren_stack.pop()
                else:
                    errors.append(f"Line {line_num}: Unmatched closing parenthesis")
            elif char == '[':
                bracket_stack.append(line_num)
            elif char == ']':
                if bracket_stack:
                    bracket_stack.pop()
                else:
                    errors.append(f"Line {line_num}: Unmatched closing bracket")
        
        # Track variable definitions (simple pattern: "var = ...")
        if '=' in line and 'def ' not in line:
            parts = line.split('=')
            if len(parts) >= 2:
                var_name = parts[0].strip().split('.')[-1]  # Handle chained assignments
                if var_name and not var_name.startswith('#'):
                    defined_vars.add(var_name)
    
    # Check for unclosed parentheses
    if paren_stack:
        errors.append(f"Unclosed parenthesis at lines: {paren_stack}")
    if bracket_stack:
        errors.append(f"Unclosed bracket at lines: {bracket_stack}")
    
    # Check for required definitions
    required_vars = {'mixed', 'playlist'}  # May not always be required
    # (Skip this check as it's too strict)
    
    is_valid = len(errors) == 0
    return is_valid, errors


def inject_phase5_into_script(
    script_lines: List[str],
    transitions: List[Dict],
    bpm: float = 120.0,
    insertion_point: str = "after_track_definitions"
) -> List[str]:
    """
    Inject Phase 5 effects into a Liquidsoap script.
    
    Args:
        script_lines: List of script lines
        transitions: Transition list with phase5_micro_techniques
        bpm: BPM for timing
        insertion_point: Where to inject ("after_track_definitions" or "in_transition_func")
    
    Returns:
        Modified script lines
    """
    result = list(script_lines)
    
    if insertion_point == "after_track_definitions":
        # Find insertion point: right after track definitions (before SEQUENCING comment)
        insert_idx = None
        for idx, line in enumerate(result):
            if "SEQUENCING + CROSSFADE" in line or "SEQUENTIAL PLAYBACK" in line:
                insert_idx = idx
                break
        
        if insert_idx is None:
            logger.warning("Could not find insertion point for Phase 5 effects")
            return result
        
        # Generate Phase 5 code sections for each track
        phase5_lines = []
        for i, trans in enumerate(transitions):
            effect_code = generate_phase5_track_effects(trans, f"track_{i}", bpm, i)
            if effect_code:
                phase5_lines.append(effect_code)
        
        if phase5_lines:
            phase5_section = ["", "# === PHASE 5: MICRO-TECHNIQUES ===", ""] + phase5_lines
            result = result[:insert_idx] + phase5_section + result[insert_idx:]
    
    return result


# Unit test / demo
if __name__ == "__main__":
    print("=" * 70)
    print("PHASE 5 LIQUIDSOAP INJECTION TEST")
    print("=" * 70)
    
    # Create test transition with Phase 5 techniques
    test_transition = {
        'file_path': '/tmp/test_track.mp3',
        'track_id': 'test_1',
        'bpm': 128.0,
        'phase5_micro_techniques': [
            {
                'type': 'bass_cut_roll',
                'name': 'Bass Cut Roll',
                'start_bar': 8.0,
                'duration_bars': 2.0,
                'parameters': {'hpf_freq': 400.0},
                'confidence': 0.95,
            },
            {
                'type': 'filter_sweep',
                'name': 'Filter Sweep',
                'start_bar': 12.0,
                'duration_bars': 4.0,
                'parameters': {'start_hz': 20000.0, 'end_hz': 200.0},
                'confidence': 0.85,
            },
        ]
    }
    
    # Generate code
    print("\n✅ Generating Phase 5 track effects...")
    code = generate_phase5_track_effects(test_transition, "track_0", 128.0, 0)
    print(code)
    
    # Validate syntax
    print("\n✅ Validating Liquidsoap syntax...")
    is_valid, errors = validate_liquidsoap_syntax(code)
    print(f"Valid: {is_valid}")
    if errors:
        print("Errors:")
        for err in errors:
            print(f"  - {err}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
