#!/usr/bin/env python3
"""
Phase 5 Integration Test - Verify rendering pipeline integration
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# Test imports
try:
    from src.autodj.render.render import apply_phase5_micro_techniques
    from src.autodj.render.phase5_integration import Phase5Renderer
    from src.autodj.generate.personas import DJPersona, get_persona_config, list_personas
    print("✅ All Phase 5 imports successful")
except Exception as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def test_phase5_integration():
    """Test Phase 5 integration with mock transitions"""
    
    print("\n" + "=" * 70)
    print("🎵 PHASE 5 INTEGRATION TEST")
    print("=" * 70)
    
    # Create mock transitions
    transitions = [
        {
            'index': 0,
            'track_id': 'track_1',
            'title': 'Deep Tech Start',
            'bpm': 125,
            'target_bpm': 125,
            'duration_seconds': 30.0,
            'file_path': '/tmp/mock_track_1.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
        },
        {
            'index': 1,
            'track_id': 'track_2',
            'title': 'Tech House Peak',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 32.0,
            'file_path': '/tmp/mock_track_2.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
        },
        {
            'index': 2,
            'track_id': 'track_3',
            'title': 'Minimal Groove',
            'bpm': 120,
            'target_bpm': 120,
            'duration_seconds': 28.0,
            'file_path': '/tmp/mock_track_3.mp3',
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
    
    print("\n📊 Test Parameters:")
    print(f"  - Transitions: {len(transitions)}")
    print(f"  - Duration: {sum(t['duration_seconds'] for t in transitions):.0f} seconds")
    print(f"  - Average BPM: {sum(t['bpm'] for t in transitions) / len(transitions):.0f}")
    
    # Test each persona
    personas_to_test = [
        ("tech_house", "Tech House Energy"),
        ("high_energy", "Hard Techno Assault"),
        ("minimal", "Minimal Hypnotic"),
        ("acid", "Acid Squelch"),
    ]
    
    all_passed = True
    
    for persona_name, persona_display in personas_to_test:
        print(f"\n\n🎭 Testing: {persona_display}")
        print("-" * 70)
        
        try:
            # Apply Phase 5 with persona
            updated_transitions, metrics = apply_phase5_micro_techniques(
                transitions,
                config,
                persona=persona_name,
                seed=42
            )
            
            # Verify results
            techniques_found = 0
            for trans in updated_transitions:
                if 'phase5_micro_techniques' in trans:
                    techniques_found += len(trans['phase5_micro_techniques'])
            
            print(f"\n✅ Phase 5 Applied Successfully")
            print(f"   Total techniques selected: {techniques_found}")
            print(f"   Transitions with techniques: {metrics.get('transitions_with_techniques', 0)}/{len(transitions)}")
            
            # Show technique breakdown
            if metrics.get('by_type'):
                print(f"\n   Technique Breakdown:")
                for tech_name, count in sorted(metrics['by_type'].items(), key=lambda x: -x[1]):
                    print(f"     - {tech_name}: {count}")
            
            # Verify persona config
            persona_config = get_persona_config(DJPersona[persona_name.upper().replace("-", "_")])
            print(f"\n   Persona Details:")
            print(f"     - Selector: {persona_config.selector_mode}")
            print(f"     - Energy Build: {persona_config.energy_build}")
            print(f"     - Effect Frequency: {persona_config.technique_frequency*100:.0f}%")
            
        except Exception as e:
            print(f"\n❌ Phase 5 Failed for {persona_display}")
            print(f"   Error: {e}")
            all_passed = False
    
    print("\n" + "=" * 70)
    
    if all_passed:
        print("✅ ALL PHASE 5 INTEGRATION TESTS PASSED!")
        return True
    else:
        print("❌ SOME TESTS FAILED")
        return False

if __name__ == "__main__":
    success = test_phase5_integration()
    sys.exit(0 if success else 1)
