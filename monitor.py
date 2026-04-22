#!/usr/bin/env python3
"""
Real-Time Monitoring Dashboard for Multi-Loop Deployment

Monitors:
1. Analysis progress (tracks processed)
2. BPM fallback statistics
3. Loop stability scoring
4. Performance metrics
"""

import sys
import time
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def parse_log_file(log_path):
    """Parse analysis log and extract statistics"""
    
    stats = {
        'total_tracks': 0,
        'bpm_detected': 0,
        'bpm_fallback': 0,
        'key_detected': 0,
        'key_unknown': 0,
        'structure_analyzed': 0,
        'loops_detected': [],
        'errors': [],
        'timestamps': defaultdict(int),
    }
    
    if not Path(log_path).exists():
        return stats
    
    try:
        with open(log_path, 'r') as f:
            for line in f:
                # Count BPM detections
                if '✅ BPM detected:' in line:
                    stats['bpm_detected'] += 1
                    stats['total_tracks'] += 1
                
                # Count BPM fallbacks
                if '⚠️ BPM detection failed' in line:
                    stats['bpm_fallback'] += 1
                    stats['total_tracks'] += 1
                
                # Count key detections
                if 'key detection failed' in line.lower():
                    stats['key_unknown'] += 1
                else:
                    if 'key' in line.lower() and stats['bpm_detected'] > stats['key_detected']:
                        stats['key_detected'] += 1
                
                # Count structure analysis
                if 'Analyzing structure' in line or 'analyze_track_structure' in line:
                    stats['structure_analyzed'] += 1
                
                # Extract loop info
                if 'LoopRegion' in line or 'loop_regions' in line:
                    stats['loops_detected'].append(line.strip())
                
                # Track errors
                if 'ERROR' in line or 'FAILED' in line:
                    stats['errors'].append(line.strip())
                
    except Exception as e:
        print(f"Error parsing log: {e}")
    
    return stats

def print_dashboard(stats, elapsed_time=None):
    """Print formatted monitoring dashboard"""
    
    print("\n" + "=" * 80)
    print("🎵 MULTI-LOOP DEPLOYMENT MONITORING DASHBOARD")
    print("=" * 80)
    
    if elapsed_time:
        print(f"⏱️  Elapsed Time: {elapsed_time:.1f} seconds")
    
    print(f"\n📊 ANALYSIS PROGRESS")
    print("-" * 80)
    print(f"   Total Tracks Processed: {stats['total_tracks']}")
    
    # BPM Statistics
    print(f"\n🎵 BPM DETECTION (Issue #1 Monitoring)")
    print("-" * 80)
    print(f"   ✅ BPM Detected (normal):    {stats['bpm_detected']:4d} tracks")
    print(f"   ⚠️  BPM Fallback (120 BPM):  {stats['bpm_fallback']:4d} tracks")
    
    total_bpm = stats['bpm_detected'] + stats['bpm_fallback']
    if total_bpm > 0:
        detection_rate = (stats['bpm_detected'] / total_bpm) * 100
        fallback_rate = (stats['bpm_fallback'] / total_bpm) * 100
        print(f"   📈 Detection Rate: {detection_rate:.1f}% | Fallback Rate: {fallback_rate:.1f}%")
        
        if stats['bpm_fallback'] > 0:
            print(f"   ℹ️  Recovery (from skipping): +{stats['bpm_fallback']} tracks")
    
    # Key Statistics
    print(f"\n🎼 KEY DETECTION")
    print("-" * 80)
    print(f"   ✅ Keys Detected:  {stats['key_detected']:4d} tracks")
    print(f"   ❓ Unknown Keys:   {stats['key_unknown']:4d} tracks")
    
    # Structure Analysis
    print(f"\n🏗️  STRUCTURE ANALYSIS (Issue #2 Monitoring)")
    print("-" * 80)
    print(f"   Sections Analyzed:  {stats['structure_analyzed']:4d} tracks")
    print(f"   Loops Detected:     {len(stats['loops_detected']):4d} entries")
    
    # Error Summary
    if stats['errors']:
        print(f"\n⚠️  ERRORS ({len(stats['errors'])} found)")
        print("-" * 80)
        for error in stats['errors'][:5]:
            print(f"   {error}")
        if len(stats['errors']) > 5:
            print(f"   ... and {len(stats['errors']) - 5} more")
    else:
        print(f"\n✅ NO ERRORS DETECTED")
    
    print("\n" + "=" * 80)

def monitor_analysis(log_path, update_interval=5):
    """Real-time monitoring with updates"""
    
    print(f"\n🚀 Starting real-time monitoring of: {log_path}")
    print(f"Update interval: {update_interval} seconds")
    print(f"Press Ctrl+C to stop monitoring\n")
    
    last_line_count = 0
    start_time = time.time()
    
    try:
        while True:
            stats = parse_log_file(log_path)
            elapsed = time.time() - start_time
            
            # Check if log file changed
            if Path(log_path).exists():
                current_line_count = sum(1 for _ in open(log_path))
                if current_line_count != last_line_count or elapsed < 10:
                    print_dashboard(stats, elapsed)
                    last_line_count = current_line_count
            
            time.sleep(update_interval)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
        final_stats = parse_log_file(log_path)
        print_dashboard(final_stats, time.time() - start_time)
        return final_stats

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor multi-loop deployment")
    parser.add_argument("log_file", nargs="?", help="Log file to monitor")
    parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    
    args = parser.parse_args()
    
    # Default to most recent analysis log
    if not args.log_file:
        log_dir = Path("/tmp")
        logs = list(log_dir.glob("multiloop-analysis-*.log"))
        if logs:
            args.log_file = str(max(logs, key=lambda p: p.stat().st_mtime))
            print(f"Using latest log: {args.log_file}")
        else:
            print("Error: No analysis log found. Run 'make analyze' first.")
            sys.exit(1)
    
    if args.once:
        stats = parse_log_file(args.log_file)
        print_dashboard(stats)
    else:
        monitor_analysis(args.log_file, args.interval)
