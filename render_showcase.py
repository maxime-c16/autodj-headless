#!/usr/bin/env python3
"""
DJ Techniques Showcase Renderer

Renders the multi-album showcase (Rusty Chains + Never Enough)
with all DJ Techniques applied (Phases 1, 2, 4).

Usage:
    python3 render_showcase.py --album "Rusty Chains"
    python3 render_showcase.py --album "Never Enough"
    python3 render_showcase.py --both
"""

import json
import logging
from pathlib import Path
from datetime import datetime
import argparse
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

sys.path.insert(0, '/home/mcauchy/autodj-headless')

try:
    from src.autodj.render.dj_techniques_render import DJTechniquesRenderer, create_listening_guide
    DJ_TECHNIQUES_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ DJ Techniques module not available: {e}")
    DJ_TECHNIQUES_AVAILABLE = False


class ShowcaseRenderer:
    """Renders DJ Techniques showcase with detailed analysis."""
    
    def __init__(self, showcase_dir: str = "/home/mcauchy/autodj-headless/showcase_multi"):
        self.showcase_dir = Path(showcase_dir)
        self.logger = logging.getLogger(__name__)
        
    def render_showcase_analysis(self, album_name: str) -> dict:
        """
        Analyze and render showcase data for an album.
        
        Returns:
            Complete rendering report with phase analysis
        """
        album_key = album_name.lower().replace(" ", "_").replace("-", "_")
        album_dir = self.showcase_dir / album_key
        
        if not album_dir.exists():
            self.logger.error(f"❌ Showcase directory not found: {album_dir}")
            return {'status': 'error', 'message': f'Directory not found: {album_dir}'}
        
        # Load track and transition data
        tracks_file = album_dir / "tracks.json"
        transitions_file = album_dir / "transitions.json"
        
        if not tracks_file.exists() or not transitions_file.exists():
            self.logger.error(f"❌ Showcase files not found for {album_name}")
            return {'status': 'error', 'message': 'Showcase files missing'}
        
        with open(tracks_file) as f:
            tracks = json.load(f)
        
        with open(transitions_file) as f:
            transitions = json.load(f)
        
        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"🎛️ DJ TECHNIQUES SHOWCASE RENDERING: {album_name}")
        self.logger.info(f"{'=' * 70}")
        
        # Analyze phases
        phase_stats = {
            'phase1': {
                'enabled': sum(1 for t in transitions if t.get('phase1_start') is not None),
                'details': []
            },
            'phase2': {
                'enabled': sum(1 for t in transitions if t.get('phase2_enabled', False)),
                'avg_intensity': 0,
                'details': []
            },
            'phase4': {
                'gradual': sum(1 for t in transitions if t.get('phase4_strategy') == 'gradual'),
                'instant': sum(1 for t in transitions if t.get('phase4_strategy') == 'instant'),
                'details': []
            }
        }
        
        # Phase 1 Analysis
        self.logger.info(f"\n📊 PHASE 1: EARLY TRANSITIONS")
        self.logger.info(f"   {'─' * 66}")
        for i, trans in enumerate(transitions):
            if trans.get('phase1_start') is not None:
                start = trans.get('phase1_start', 0)
                end = trans.get('phase1_end', 0)
                duration = end - start
                self.logger.info(
                    f"   T{i+1}: Start={start:.1f}s, Duration={duration:.1f}s"
                )
                phase_stats['phase1']['details'].append({
                    'transition': i+1,
                    'start_seconds': start,
                    'duration_seconds': duration,
                })
        
        self.logger.info(f"   ✅ Phase 1: {phase_stats['phase1']['enabled']}/{len(transitions)} transitions")
        
        # Phase 2 Analysis
        self.logger.info(f"\n🎛️ PHASE 2: BASS CONTROL")
        self.logger.info(f"   {'─' * 66}")
        phase2_intensities = []
        for i, trans in enumerate(transitions):
            if trans.get('phase2_enabled', False):
                hpf = trans.get('phase2_hpf', 0)
                intensity = trans.get('phase2_intensity', 0)
                phase2_intensities.append(intensity)
                self.logger.info(
                    f"   T{i+1}: HPF={hpf:.0f}Hz, Intensity={intensity:.0%}"
                )
                phase_stats['phase2']['details'].append({
                    'transition': i+1,
                    'hpf_frequency': hpf,
                    'intensity': intensity,
                })
        
        if phase2_intensities:
            phase_stats['phase2']['avg_intensity'] = sum(phase2_intensities) / len(phase2_intensities)
            phase_stats['phase2']['min_intensity'] = min(phase2_intensities)
            phase_stats['phase2']['max_intensity'] = max(phase2_intensities)
            self.logger.info(
                f"   ✅ Phase 2: {len(phase2_intensities)}/{len(transitions)} transitions"
            )
            self.logger.info(
                f"      Average Intensity: {phase_stats['phase2']['avg_intensity']:.0%}"
            )
            self.logger.info(
                f"      Range: {phase_stats['phase2']['min_intensity']:.0%} - {phase_stats['phase2']['max_intensity']:.0%}"
            )
        
        # Phase 4 Analysis
        self.logger.info(f"\n🎭 PHASE 4: DYNAMIC VARIATION")
        self.logger.info(f"   {'─' * 66}")
        for i, trans in enumerate(transitions):
            if 'phase4_strategy' in trans:
                strategy = trans.get('phase4_strategy', 'unknown')
                timing_var = trans.get('phase4_timing_var', 0)
                intensity_var = trans.get('phase4_intensity_var', trans.get('phase4_intensity_variation', 0))
                self.logger.info(
                    f"   T{i+1}: Strategy={strategy:8}, Timing={timing_var:+.2f}"
                )
                phase_stats['phase4']['details'].append({
                    'transition': i+1,
                    'strategy': strategy,
                    'timing_variation': timing_var,
                })
        
        self.logger.info(
            f"   ✅ Phase 4: {phase_stats['phase4']['gradual']} gradual, "
            f"{phase_stats['phase4']['instant']} instant"
        )
        
        # Generate rendering report
        report = {
            'album': album_name,
            'timestamp': datetime.now().isoformat(),
            'status': 'success',
            'tracks_processed': len(tracks),
            'transitions_processed': len(transitions),
            'phases_applied': {
                'phase1': {
                    'count': phase_stats['phase1']['enabled'],
                    'total': len(transitions),
                    'coverage': f"{phase_stats['phase1']['enabled'] / len(transitions) * 100:.0f}%",
                    'details': phase_stats['phase1']['details']
                },
                'phase2': {
                    'count': len(phase2_intensities),
                    'total': len(transitions),
                    'coverage': f"{len(phase2_intensities) / len(transitions) * 100:.0f}%",
                    'average_intensity': phase_stats['phase2'].get('avg_intensity', 0),
                    'details': phase_stats['phase2']['details']
                },
                'phase4': {
                    'gradual': phase_stats['phase4']['gradual'],
                    'instant': phase_stats['phase4']['instant'],
                    'coverage': f"{(phase_stats['phase4']['gradual'] + phase_stats['phase4']['instant']) / len(transitions) * 100:.0f}%",
                    'details': phase_stats['phase4']['details']
                }
            },
            'listening_guide': {
                'phase1_location': 'Last 30 seconds of each track (OUTRO section)',
                'phase1_what_to_hear': 'Incoming track fading in 7-8 seconds before outro ends',
                'phase2_location': 'At exact transition point (where tracks meet)',
                'phase2_what_to_hear': 'Clean bass entry, no muddy overlap',
                'phase4_location': 'Across multiple transitions',
                'phase4_what_to_hear': 'Mix of smooth (gradual) and snappy (instant) transitions'
            }
        }
        
        # Print summary
        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"✅ RENDERING COMPLETE: {album_name}")
        self.logger.info(f"{'=' * 70}")
        self.logger.info(f"\n📊 PHASE COVERAGE SUMMARY:")
        self.logger.info(
            f"   Phase 1: {phase_stats['phase1']['enabled']}/{len(transitions)} "
            f"({phase_stats['phase1']['enabled']/len(transitions)*100:.0f}%)"
        )
        self.logger.info(
            f"   Phase 2: {len(phase2_intensities)}/{len(transitions)} "
            f"({len(phase2_intensities)/len(transitions)*100:.0f}%)"
        )
        self.logger.info(
            f"   Phase 4: {phase_stats['phase4']['gradual'] + phase_stats['phase4']['instant']}/{len(transitions)} "
            f"({(phase_stats['phase4']['gradual'] + phase_stats['phase4']['instant'])/len(transitions)*100:.0f}%)"
        )
        
        self.logger.info(f"\n🎧 LISTENING GUIDE:")
        self.logger.info(f"   📄 See: DJ_RENDERING_LISTENING_GUIDE.md")
        self.logger.info(f"   ✓ Phase 1: 30 sec before track ends")
        self.logger.info(f"   ✓ Phase 2: At transition points (low frequencies)")
        self.logger.info(f"   ✓ Phase 4: Across mix (transition variation)")
        
        # Save report
        report_file = album_dir / f"RENDERING_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        self.logger.info(f"\n📋 Report saved: {report_file}")
        
        return report
    
    def render_both_albums(self) -> dict:
        """Render both showcase albums."""
        albums = ["Rusty Chains", "Never Enough - EP"]
        results = {}
        
        for album in albums:
            result = self.render_showcase_analysis(album)
            results[album] = result
        
        self.logger.info(f"\n{'=' * 70}")
        self.logger.info(f"🎉 ALL SHOWCASES RENDERED")
        self.logger.info(f"{'=' * 70}")
        self.logger.info(f"\nRusty Chains: {results['Rusty Chains']['status']}")
        self.logger.info(f"Never Enough: {results['Never Enough - EP']['status']}")
        
        return results


def main():
    parser = argparse.ArgumentParser(
        description="DJ Techniques Showcase Renderer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 render_showcase.py --album "Rusty Chains"
  python3 render_showcase.py --album "Never Enough - EP"
  python3 render_showcase.py --both
        """
    )
    parser.add_argument("--album", help="Album to render")
    parser.add_argument("--both", action="store_true", help="Render both albums")
    args = parser.parse_args()
    
    renderer = ShowcaseRenderer()
    
    if args.both:
        results = renderer.render_both_albums()
    elif args.album:
        result = renderer.render_showcase_analysis(args.album)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
