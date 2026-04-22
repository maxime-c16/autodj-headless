#!/usr/bin/env python3
"""
Phase 1 Integration Test - Verify rendering pipeline integration with early transitions
"""

import json
import sys
from pathlib import Path

def test_phase1_integration():
    """Test Phase 1 integration with mock transitions"""
    
    print("\n" + "=" * 80)
    print("🎵 PHASE 1 EARLY TRANSITIONS INTEGRATION TEST")
    print("=" * 80)
    
    from src.autodj.render.render import apply_phase1_early_transitions
    
    # Create mock transitions
    print("\n📊 STEP 1: Creating Mock Transitions")
    print("-" * 80)
    
    transitions = [
        {
            'index': 0,
            'track_id': 'track_1',
            'title': 'Tech House Intro',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 300.0,
            'file_path': '/tmp/track1.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
            'outro_start_seconds': 260.0,  # Outro starts at 260s
        },
        {
            'index': 1,
            'track_id': 'track_2',
            'title': 'Tech House Peak',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 320.0,
            'file_path': '/tmp/track2.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
            'outro_start_seconds': 280.0,  # Outro starts at 280s
        },
        {
            'index': 2,
            'track_id': 'track_3',
            'title': 'Tech House Breakdown',
            'bpm': 128,
            'target_bpm': 128,
            'duration_seconds': 280.0,
            'file_path': '/tmp/track3.mp3',
            'transition_type': 'bass_swap',
            'overlap_bars': 8,
            'outro_start_seconds': 240.0,  # Outro starts at 240s
        },
    ]
    
    # Create track info dict
    outgoing_tracks = {
        'track_1': {
            'id': 'track_1',
            'title': 'Tech House Intro',
            'duration_seconds': 300.0,
            'outro_start_seconds': 260.0,
        },
        'track_2': {
            'id': 'track_2',
            'title': 'Tech House Peak',
            'duration_seconds': 320.0,
            'outro_start_seconds': 280.0,
        },
        'track_3': {
            'id': 'track_3',
            'title': 'Tech House Breakdown',
            'duration_seconds': 280.0,
            'outro_start_seconds': 240.0,
        },
    }
    
    config = {
        'render': {
            'output_format': 'mp3',
            'mp3_bitrate': 320,
        }
    }
    
    print(f"✅ Created {len(transitions)} mock transitions")
    print(f"   BPM: 128 (house tempo)")
    print(f"   Overlap: 8 bars")
    
    # Test each Phase 1 model
    models = [
        "fixed_16_bars",
        "fixed_24_bars",
        "fixed_32_bars",
    ]
    
    all_passed = True
    
    for model in models:
        print(f"\n\n🎭 Testing Model: {model}")
        print("-" * 80)
        
        try:
            updated_transitions, metrics = apply_phase1_early_transitions(
                transitions,
                outgoing_tracks,
                config,
                phase1_enabled=True,
                phase1_model=model
            )
            
            print(f"\n✅ Phase 1 Applied Successfully")
            print(f"   Total transitions: {metrics.get('total_transitions', 0)}")
            print(f"   With early timing: {metrics.get('transitions_with_early_timing', 0)}")
            print(f"   Outros detected: {metrics.get('outro_detected_count', 0)}")
            print(f"   Avg early start: {metrics.get('average_early_start_seconds', 0):.1f}s")
            
            # Show timing details
            if metrics.get('timing_by_transition'):
                print(f"\n   Timing Details:")
                for timing in metrics['timing_by_transition']:
                    print(f"     [{timing['index']}] {timing['title']}")
                    print(f"         Outro @ {timing['outro_start']:.1f}s")
                    print(f"         Early start @ {timing['crossfade_start']:.1f}s")
                    print(f"         {timing['early_bars']} bars before outro")
            
            # Verify phase1_metadata is in transitions
            transitions_with_metadata = sum(1 for t in updated_transitions if 'phase1_metadata' in t)
            print(f"\n   Transitions with metadata: {transitions_with_metadata}/{len(updated_transitions)}")
            
            if transitions_with_metadata > 0:
                print("   ✅ Phase 1 metadata correctly stored in transitions")
            else:
                print("   ⚠️ No Phase 1 metadata found in transitions")
                all_passed = False
            
        except Exception as e:
            print(f"❌ Phase 1 Failed for {model}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print("\n" + "=" * 80)
    
    if all_passed:
        print("✅ ALL PHASE 1 INTEGRATION TESTS PASSED!")
        return True
    else:
        print("❌ SOME TESTS FAILED")
        return False

if __name__ == "__main__":
    try:
        success = test_phase1_integration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
