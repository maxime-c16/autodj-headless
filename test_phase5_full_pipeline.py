#!/usr/bin/env python3
"""
Full Phase 5 Rendering Pipeline Test
Tests the complete flow from transitions to Liquidsoap script generation
"""

import json
import sys
from pathlib import Path

def test_full_pipeline():
    """Test complete rendering pipeline with Phase 5"""
    
    print("\n" + "=" * 80)
    print("🎵 FULL PHASE 5 RENDERING PIPELINE TEST")
    print("=" * 80)
    
    from src.autodj.render.render import apply_phase5_micro_techniques
    from src.autodj.render.phase5_liquidsoap_codegen import generate_phase5_liquidsoap
    from src.autodj.generate.personas import get_persona_config, DJPersona
    
    # Step 1: Create mock transitions
    print("\n📊 STEP 1: Creating Mock Transitions")
    print("-" * 80)
    
    transitions = [
        {
            'index': 0,
            'track_id': 'track_1',
            'title': 'Tech House Intro',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 32.0,
            'file_path': '/tmp/track1.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
        },
        {
            'index': 1,
            'track_id': 'track_2',
            'title': 'Tech House Peak',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 30.0,
            'file_path': '/tmp/track2.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
        },
    ]
    
    config = {
        'render': {
            'output_format': 'mp3',
            'mp3_bitrate': 320,
        }
    }
    
    print(f"✅ Created {len(transitions)} mock transitions")
    
    # Step 2: Apply Phase 5 with persona
    print("\n🎭 STEP 2: Applying Phase 5 with Tech House Persona")
    print("-" * 80)
    
    updated_transitions, metrics = apply_phase5_micro_techniques(
        transitions,
        config,
        persona="tech_house",
        seed=42
    )
    
    print(f"✅ Phase 5 applied: {metrics.get('total_techniques_selected', 0)} techniques selected")
    
    # Step 3: Generate Liquidsoap code for each transition
    print("\n🎛️  STEP 3: Generating Liquidsoap Code for Phase 5 Techniques")
    print("-" * 80)
    
    persona_config = get_persona_config(DJPersona.TECH_HOUSE)
    
    all_scripts = []
    
    for idx, trans in enumerate(updated_transitions):
        phase5_techniques = trans.get("phase5_micro_techniques")
        
        if phase5_techniques:
            bpm = trans.get("target_bpm", trans.get("bpm", 120.0))
            overlap_bars = trans.get("overlap_bars", 8)
            
            liquidsoap_code = generate_phase5_liquidsoap(
                phase5_techniques,
                transition_var=f"transition_{idx}_{idx+1}",
                bpm=bpm,
                overlap_bars=overlap_bars
            )
            
            all_scripts.append(liquidsoap_code)
            
            print(f"\n📍 Transition {idx}->{idx+1}:")
            print(f"   Techniques: {len(phase5_techniques)}")
            for tech in phase5_techniques:
                print(f"   - {tech['name']} @ bar {tech['start_bar']:.1f}")
            print(f"   Liquidsoap lines: {len(liquidsoap_code.split(chr(10)))}")
    
    # Step 4: Verify script integrity
    print("\n✔️  STEP 4: Verifying Liquidsoap Script Integrity")
    print("-" * 80)
    
    all_code = "\n\n".join(all_scripts)
    
    # Check for critical patterns
    checks = {
        'Bass Cut Roll generated': 'filter.iir.butterworth.high' in all_code,
        'Stutter/Loop Roll generated': 'Stutter Roll:' in all_code or 'Bass Cut Roll:' in all_code,
        'Timing comments present': '# [1]' in all_code,
        'Variable references correct': 'transition_' in all_code,
        'Frequency parameters present': 'frequency=' in all_code,
    }
    
    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check_name}")
        if not passed:
            all_passed = False
    
    # Step 5: Show generated code sample
    print("\n📄 STEP 5: Generated Liquidsoap Code Sample")
    print("-" * 80)
    
    code_lines = all_code.split('\n')
    sample_start = 0
    sample_lines = code_lines[sample_start:sample_start+15]
    
    for line in sample_lines:
        print(line)
    
    if len(code_lines) > 15:
        print(f"   ... ({len(code_lines) - 15} more lines)")
    
    # Step 6: Persona configuration summary
    print("\n🎭 STEP 6: Persona Configuration Applied")
    print("-" * 80)
    
    print(f"   Persona: {persona_config.name}")
    print(f"   Selector: {persona_config.selector_mode}")
    print(f"   Energy Build: {persona_config.energy_build}")
    print(f"   Effect Frequency: {persona_config.technique_frequency*100:.0f}%")
    print(f"   Duration Multiplier: {persona_config.technique_duration_multiplier}x")
    print(f"   Spacing: {persona_config.min_technique_interval_bars}-{persona_config.max_technique_interval_bars} bars")
    
    # Final result
    print("\n" + "=" * 80)
    
    if all_passed:
        print("✅ FULL RENDERING PIPELINE TEST PASSED!")
        print("\n🎵 Ready to render with Phase 5 micro-techniques!")
        return True
    else:
        print("❌ SOME CHECKS FAILED")
        return False

if __name__ == "__main__":
    try:
        success = test_full_pipeline()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
