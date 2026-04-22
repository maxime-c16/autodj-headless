#!/usr/bin/env python3
"""
AutoDJ Render with All Phases Enabled (Phase 1 + Phase 5)
Uses the enhanced transitions metadata generated today
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Set Python path to use local autodj module
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

def main():
    print("\n" + "=" * 80)
    print("🎵 AUTODJ RENDER - ALL PHASES ENABLED (Phase 1 + Phase 5)")
    print("=" * 80)
    
    # Load the enhanced transitions
    transitions_file = Path("/home/mcauchy/autodj-headless/data/playlists/transitions-20260224-WITH-PHASES.json")
    
    if not transitions_file.exists():
        print(f"❌ Transitions file not found: {transitions_file}")
        return False
    
    print(f"\n📂 Loading transitions: {transitions_file}")
    
    with open(transitions_file, 'r') as f:
        data = json.load(f)
    
    print(f"✅ Loaded {len(data['transitions'])} transitions")
    print(f"   Duration: {data['mix_duration_seconds']/60:.1f} minutes")
    
    # Prepare output to NAS
    output_dir = Path("/srv/nas/shared/automix")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_file = output_dir / f"autodj-mix-{timestamp}-with-phases.mp3"
    
    print(f"\n🎬 Rendering to: {output_file}")
    
    # Import and call render
    try:
        from autodj.render.render import render
        
        config = {
            'render': {
                'output_format': 'mp3',
                'mp3_bitrate': 320,
                'output_path': str(output_dir),
            }
        }
        
        print("\n📊 Render Configuration:")
        print("   Phase 0: Precision fixes ✅")
        print("   Phase 1: Early transitions (16-bar) ✅")
        print("   Phase 2: DJ EQ annotation ✅")
        print("   Phase 4: Variations ✅")
        print("   Phase 5: Micro-techniques (tech_house) ✅")
        
        print("\n🎬 Starting render...")
        print("-" * 80)
        
        success = render(
            transitions_json_path=str(transitions_file),
            output_path=str(output_file),
            config=config,
            timeout_seconds=None,  # No timeout
            eq_enabled=True,  # Re-enabled - was working before
            eq_strategy="ladspa",
            precision_fixes_enabled=True,
            confidence_validator_enabled=True,
            bpm_multipass_enabled=True,
            grid_validation_enabled=True,
            phase1_enabled=True,
            phase1_model="fixed_16_bars",
            phase5_enabled=True,
            persona="tech_house",
        )
        
        print("-" * 80)
        
        if success:
            print("\n✅ RENDER COMPLETE!")
            
            if output_file.exists():
                size_mb = output_file.stat().st_size / (1024 * 1024)
                print(f"\n🎵 Output: {output_file}")
                print(f"   Size: {size_mb:.1f} MB")
                print(f"   Format: MP3 320 kbps")
                print(f"   Status: ✅ Ready to listen!")
                return True
            else:
                print(f"\n⚠️ Output file not found at: {output_file}")
                return False
        else:
            print("\n❌ Render returned False")
            return False
            
    except Exception as e:
        print(f"\n❌ Render error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
