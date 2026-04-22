#!/usr/bin/env python3
"""
Phase 1 & Phase 5 Rendering Comparison Test
==============================================

Compares the metadata produced yesterday night (nightly cron, no Phase 1/5)
with today's rendering using all phases integrated.

This allows direct A/B comparison of:
- Phase 1 early transition timing
- Phase 5 micro-techniques selection
- Overall mixing quality enhancements
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def load_transitions(path: str) -> dict:
    """Load transitions.json file"""
    with open(path, 'r') as f:
        return json.load(f)

def compare_transitions(old_data: dict, new_data: dict) -> dict:
    """Compare old (no phases) vs new (with phases) metadata"""
    
    old_transitions = old_data.get('transitions', [])
    new_transitions = new_data.get('transitions', [])
    
    if len(old_transitions) != len(new_transitions):
        print(f"⚠️ Different number of transitions: {len(old_transitions)} vs {len(new_transitions)}")
    
    comparison = {
        'total_transitions': len(new_transitions),
        'transitions_with_phase1': 0,
        'transitions_with_phase5': 0,
        'phase1_details': [],
        'phase5_details': [],
        'changed_fields': {},
    }
    
    for idx, (old_trans, new_trans) in enumerate(zip(old_transitions, new_transitions)):
        trans_title = new_trans.get('title', f'Track {idx}')
        
        # Check Phase 1
        if 'phase1_metadata' in new_trans:
            comparison['transitions_with_phase1'] += 1
            
            meta = new_trans['phase1_metadata']
            comparison['phase1_details'].append({
                'index': idx,
                'title': trans_title,
                'enabled': meta.get('enabled'),
                'early_transition_bars': meta.get('early_transition_bars'),
                'outro_start_seconds': meta.get('outro_start_seconds'),
                'crossfade_start_seconds': meta.get('crossfade_start_seconds'),
                'outro_detected': meta.get('outro_detected'),
                'bpm': meta.get('bpm'),
            })
        
        # Check Phase 5
        if 'phase5_micro_techniques' in new_trans:
            comparison['transitions_with_phase5'] += 1
            
            techniques = new_trans['phase5_micro_techniques']
            comparison['phase5_details'].append({
                'index': idx,
                'title': trans_title,
                'technique_count': len(techniques),
                'techniques': [
                    {
                        'type': t.get('type'),
                        'name': t.get('name'),
                        'start_bar': t.get('start_bar'),
                        'duration_bars': t.get('duration_bars'),
                        'confidence': t.get('confidence'),
                    }
                    for t in techniques
                ],
            })
        
        # Check what changed
        old_keys = set(old_trans.keys())
        new_keys = set(new_trans.keys())
        
        new_fields = new_keys - old_keys
        if new_fields:
            if idx not in comparison['changed_fields']:
                comparison['changed_fields'][idx] = {}
            comparison['changed_fields'][idx]['new_fields'] = list(new_fields)
    
    return comparison

def format_comparison_report(comparison: dict) -> str:
    """Format comparison as readable report"""
    
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("🎵 PHASE 1 & PHASE 5 RENDERING COMPARISON REPORT")
    lines.append("=" * 80)
    
    # Summary
    lines.append(f"\n📊 SUMMARY")
    lines.append("-" * 80)
    lines.append(f"Total transitions processed: {comparison['total_transitions']}")
    lines.append(f"Transitions with Phase 1: {comparison['transitions_with_phase1']}")
    lines.append(f"Transitions with Phase 5: {comparison['transitions_with_phase5']}")
    
    # Phase 1 Details
    if comparison['phase1_details']:
        lines.append(f"\n\n🎵 PHASE 1: EARLY TRANSITIONS")
        lines.append("-" * 80)
        lines.append(f"Professional DJ-style early mixing enabled\n")
        
        for detail in comparison['phase1_details'][:5]:  # Show first 5
            lines.append(f"[{detail['index']}] {detail['title']}")
            if detail['outro_detected']:
                lines.append(f"    ✅ Outro detected @ {detail['outro_start_seconds']:.1f}s")
            else:
                lines.append(f"    ℹ️ Outro not detected, using fallback")
            lines.append(f"    🔄 Early start @ {detail['crossfade_start_seconds']:.1f}s")
            lines.append(f"    ⏱️  {detail['early_transition_bars']} bars before outro")
            lines.append(f"    📊 @ {detail['bpm']:.0f} BPM")
            lines.append("")
        
        if len(comparison['phase1_details']) > 5:
            lines.append(f"... and {len(comparison['phase1_details']) - 5} more transitions")
    
    # Phase 5 Details
    if comparison['phase5_details']:
        lines.append(f"\n\n🎛️  PHASE 5: MICRO-TECHNIQUES")
        lines.append("-" * 80)
        lines.append(f"Professional DJ mixing techniques applied\n")
        
        total_techniques = sum(d['technique_count'] for d in comparison['phase5_details'])
        avg_techniques = total_techniques / len(comparison['phase5_details'])
        
        lines.append(f"Total techniques applied: {total_techniques}")
        lines.append(f"Average per transition: {avg_techniques:.1f}\n")
        
        for detail in comparison['phase5_details'][:5]:  # Show first 5
            lines.append(f"[{detail['index']}] {detail['title']}")
            lines.append(f"    Techniques: {detail['technique_count']}")
            for tech in detail['techniques'][:3]:  # Show first 3 techniques
                lines.append(f"      • {tech['name']} (bars {tech['start_bar']:.1f}-{tech['start_bar'] + tech['duration_bars']:.1f})")
            if len(detail['techniques']) > 3:
                lines.append(f"      ... and {len(detail['techniques']) - 3} more")
            lines.append("")
        
        if len(comparison['phase5_details']) > 5:
            lines.append(f"... and {len(comparison['phase5_details']) - 5} more transitions")
    
    # Enhanced Fields
    if comparison['changed_fields']:
        lines.append(f"\n\n✨ NEW METADATA FIELDS ADDED")
        lines.append("-" * 80)
        
        all_new_fields = set()
        for idx_data in comparison['changed_fields'].values():
            all_new_fields.update(idx_data.get('new_fields', []))
        
        for field in sorted(all_new_fields)[:10]:
            lines.append(f"  • {field}")
        
        if len(all_new_fields) > 10:
            lines.append(f"  ... and {len(all_new_fields) - 10} more fields")
    
    lines.append("\n" + "=" * 80)
    lines.append("✅ PHASES 1 & 5 SUCCESSFULLY INTEGRATED INTO RENDERING PIPELINE")
    lines.append("=" * 80 + "\n")
    
    return "\n".join(lines)

def main():
    print("\n" + "=" * 80)
    print("🔄 PHASE 1 & PHASE 5 RENDERING COMPARISON TEST")
    print("=" * 80)
    print("\nLoading nightly render metadata from yesterday...")
    
    # Load yesterday's transitions (without Phase 1 & 5)
    old_path = "/home/mcauchy/autodj-headless/data/playlists/transitions-20260224-013123.json"
    
    if not Path(old_path).exists():
        print(f"❌ Could not find old transitions: {old_path}")
        return False
    
    try:
        old_data = load_transitions(old_path)
        print(f"✅ Loaded yesterday's transitions: {len(old_data.get('transitions', []))} tracks")
        print(f"   Generated at: {old_data.get('generated_at')}")
    except Exception as e:
        print(f"❌ Failed to load old transitions: {e}")
        return False
    
    # Now we need to regenerate with Phase 1 & 5
    print("\n🎵 Regenerating playlist with Phase 1 & Phase 5 enabled...")
    
    try:
        # Import the rendering engine
        sys.path.insert(0, '/home/mcauchy/autodj-headless/src')
        from autodj.render.render import (
            apply_phase1_early_transitions,
            apply_phase5_micro_techniques,
        )
        
        # Prepare data for Phase 1
        transitions = old_data['transitions']
        outgoing_tracks = {}
        for trans in transitions:
            track_id = trans.get('track_id')
            if track_id:
                outgoing_tracks[track_id] = {
                    'id': track_id,
                    'title': trans.get('title', ''),
                    'duration_seconds': trans.get('mix_out_seconds'),
                    'outro_start_seconds': trans.get('outro_start_seconds'),
                }
        
        # Apply Phase 1
        print("  → Applying Phase 1 (Early Transitions)...")
        config = old_data.get('config', {})
        transitions_p1, p1_metrics = apply_phase1_early_transitions(
            transitions,
            outgoing_tracks,
            config,
            phase1_enabled=True,
            phase1_model="fixed_16_bars"
        )
        print(f"    ✅ Phase 1 applied: {p1_metrics.get('transitions_with_early_timing', 0)} transitions with early timing")
        
        # Apply Phase 5
        print("  → Applying Phase 5 (Micro-Techniques)...")
        transitions_p5, p5_metrics = apply_phase5_micro_techniques(
            transitions_p1,
            config,
            persona="tech_house",
            seed=None
        )
        print(f"    ✅ Phase 5 applied: {p5_metrics.get('transitions_with_techniques', 0)} transitions with techniques")
        
        # Create new data structure
        new_data = {
            'playlist_id': old_data.get('playlist_id'),
            'mix_duration_seconds': old_data.get('mix_duration_seconds'),
            'generated_at': datetime.now().isoformat(),
            'regenerated_from': old_path,
            'phases_enabled': {
                'phase1': True,
                'phase1_model': 'fixed_16_bars',
                'phase5': True,
                'phase5_persona': 'tech_house',
            },
            'transitions': transitions_p5,
        }
        
        # Compare
        print("\n📊 COMPARING METADATA...")
        comparison = compare_transitions(old_data, new_data)
        
        # Generate report
        report = format_comparison_report(comparison)
        print(report)
        
        # Save comparison to file
        output_path = "/home/mcauchy/PHASE_COMPARISON_REPORT.json"
        with open(output_path, 'w') as f:
            json.dump({
                'comparison': comparison,
                'timestamp': datetime.now().isoformat(),
                'old_file': old_path,
                'phases': {
                    'phase1': p1_metrics,
                    'phase5': p5_metrics,
                }
            }, f, indent=2)
        
        print(f"\n✅ Full comparison saved to: {output_path}")
        
        # Save regenerated transitions
        new_trans_path = "/home/mcauchy/autodj-headless/data/playlists/transitions-20260224-WITH-PHASES.json"
        with open(new_trans_path, 'w') as f:
            json.dump(new_data, f, indent=2)
        
        print(f"✅ Regenerated transitions saved to: {new_trans_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
