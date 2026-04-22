#!/usr/bin/env python3
"""
Spectral Analysis Cache Manager
Only analyzes tracks that haven't been analyzed before.
Stores results in SQLite cache for reuse.

Usage:
    python3 spectral_cache_manager.py
    
    Or import:
    from spectral_cache_manager import SpectralCacheManager
    mgr = SpectralCacheManager()
    analysis = mgr.get_or_analyze(track_path, bpm)
"""

import sqlite3
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
import json
import os
import sys

# Add paths
sys.path.insert(0, "/app/src")

from autodj.config import Config

logger = logging.getLogger(__name__)


class SpectralCacheManager:
    """
    Smart caching for spectral analysis.
    
    - Stores analysis results in SQLite
    - Keys by file hash (detects moved/renamed files)
    - Returns cached results if track unchanged
    - Only analyzes new tracks
    - Seamless integration with quick-mix
    """
    
    def __init__(self, db_path: str = "/app/data/spectral_analysis.db"):
        """Initialize cache manager with SQLite backend"""
        self.db_path = db_path
        self._init_db()
        self._spectral_analyzer = None
    
    def _init_db(self):
        """Create spectral analysis cache table if needed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spectral_analysis_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                bpm REAL NOT NULL,
                analysis_json TEXT NOT NULL,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_seconds REAL,
                outro_start_seconds REAL,
                spectral_centroid REAL,
                onsets_count INTEGER,
                energy_rms REAL
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Spectral cache initialized: {self.db_path}")
    
    def _get_file_hash(self, file_path: str) -> str:
        """Generate hash of file for change detection"""
        # Use file path + size + mtime
        path = Path(file_path)
        if not path.exists():
            return ""
        
        stat = path.stat()
        hash_input = f"{file_path}:{stat.st_size}:{stat.st_mtime}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def _load_spectral_analyzer(self):
        """Lazy load spectral analyzer (expensive import)"""
        if self._spectral_analyzer is not None:
            return self._spectral_analyzer
        
        try:
            from autodj.render.spectral_analyzer import SpectralAnalyzer
            self._spectral_analyzer = SpectralAnalyzer()
            logger.info("✅ SpectralAnalyzer loaded")
            return self._spectral_analyzer
        except ImportError as e:
            logger.error(f"❌ Failed to import SpectralAnalyzer: {e}")
            return None
    
    def get_or_analyze(self, file_path: str, bpm: float) -> Optional[Dict[str, Any]]:
        """
        Get cached analysis or analyze if not cached.
        
        Args:
            file_path: Path to audio file
            bpm: Track BPM
        
        Returns:
            Dict with keys: outro_start_seconds, duration_seconds, spectral_centroid, etc.
            Or None if analysis failed
        """
        file_hash = self._get_file_hash(file_path)
        
        if not file_hash:
            logger.warning(f"⚠️ Could not hash file: {file_path}")
            return None
        
        # Check cache
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT analysis_json FROM spectral_analysis_cache WHERE file_hash = ?',
            (file_hash,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            analysis = json.loads(result[0])
            logger.info(f"✅ CACHED: {Path(file_path).name} @ {bpm} BPM")
            return analysis
        
        # Not cached - analyze now
        logger.info(f"📊 ANALYZING: {Path(file_path).name} @ {bpm} BPM")
        
        analyzer = self._load_spectral_analyzer()
        if not analyzer:
            logger.error(f"❌ Cannot analyze without SpectralAnalyzer")
            return None
        
        try:
            analysis = analyzer.analyze(file_path, bpm=bpm)
            
            # Store in cache
            self._store_analysis(file_hash, file_path, bpm, analysis)
            
            logger.info(f"✅ ANALYZED & CACHED: {Path(file_path).name}")
            return analysis
        
        except Exception as e:
            logger.error(f"❌ Analysis failed for {file_path}: {e}")
            return None
    
    def _store_analysis(self, file_hash: str, file_path: str, bpm: float, analysis: Dict):
        """Store analysis in cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO spectral_analysis_cache
                (file_hash, file_path, bpm, analysis_json, duration_seconds, 
                 outro_start_seconds, spectral_centroid, onsets_count, energy_rms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                file_hash,
                file_path,
                bpm,
                json.dumps(analysis),
                analysis.get('duration_seconds'),
                analysis.get('outro_start_seconds'),
                analysis.get('spectral_centroid'),
                analysis.get('onsets_count'),
                analysis.get('energy_rms'),
            ))
            
            conn.commit()
            logger.debug(f"✅ Stored in cache: {file_hash}")
        
        except Exception as e:
            logger.error(f"❌ Failed to store in cache: {e}")
        
        finally:
            conn.close()
    
    def batch_analyze(self, file_paths: list, bpm_list: list) -> Dict[str, Dict]:
        """
        Analyze multiple files (only new ones)
        
        Args:
            file_paths: List of audio file paths
            bpm_list: Corresponding BPMs
        
        Returns:
            Dict mapping file_path → analysis results
        """
        results = {}
        cached_count = 0
        analyzed_count = 0
        
        for file_path, bpm in zip(file_paths, bpm_list):
            analysis = self.get_or_analyze(file_path, bpm)
            if analysis:
                results[file_path] = analysis
                
                # Track stats
                if self._is_cached(file_path):
                    cached_count += 1
                else:
                    analyzed_count += 1
        
        # Summary
        print(f"\n{'='*70}")
        print(f"📊 SPECTRAL ANALYSIS BATCH COMPLETE")
        print(f"{'='*70}")
        print(f"  ✅ Total processed: {len(results)}")
        print(f"  📦 From cache: {cached_count}")
        print(f"  🆕 Newly analyzed: {analyzed_count}")
        print(f"  📁 Cache location: {self.db_path}")
        print(f"{'='*70}\n")
        
        return results
    
    def _is_cached(self, file_path: str) -> bool:
        """Check if file is in cache"""
        file_hash = self._get_file_hash(file_path)
        if not file_hash:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM spectral_analysis_cache WHERE file_hash = ?', (file_hash,))
        result = cursor.fetchone()
        conn.close()
        
        return result is not None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM spectral_analysis_cache')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(duration_seconds) FROM spectral_analysis_cache')
        total_duration = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            'cached_tracks': total,
            'total_duration_hours': round(total_duration / 3600, 1),
            'cache_path': self.db_path,
        }
    
    def clear_cache(self):
        """Clear entire cache (use with caution!)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM spectral_analysis_cache')
        conn.commit()
        conn.close()
        logger.warning("⚠️ Cache cleared!")


# ============================================================================
# Integration: Enhance Quick-Mix Transitions
# ============================================================================

def enhance_transitions_with_spectral_data(transitions: list) -> list:
    """
    Add spectral analysis to transitions (only new tracks).
    
    Call this in quick_mix.py before render():
    
        transitions = enhance_transitions_with_spectral_data(transitions)
        engine.render(transitions, ...)
    
    Args:
        transitions: List of transition dicts from playlist generator
    
    Returns:
        Enhanced transitions with spectral data
    """
    mgr = SpectralCacheManager()
    
    # Extract file paths and BPMs
    file_paths = [t.get('file_path') for t in transitions if t.get('file_path')]
    bpms = [t.get('bpm', 120) for t in transitions]
    
    # Batch analyze (uses cache for existing tracks)
    print("\n🔍 Checking spectral analysis cache...")
    spectral_results = mgr.batch_analyze(file_paths, bpms)
    
    # Enhance transitions with spectral data
    enhanced_transitions = []
    for i, trans in enumerate(transitions):
        file_path = trans.get('file_path')
        
        if file_path in spectral_results:
            spectral_data = spectral_results[file_path]
            
            # Add spectral fields to transition
            trans['outro_start_seconds'] = spectral_data.get('outro_start_seconds')
            trans['duration_seconds'] = spectral_data.get('duration_seconds')
            trans['spectral_centroid'] = spectral_data.get('spectral_centroid')
            trans['onsets_count'] = spectral_data.get('onsets_count')
            trans['energy_rms'] = spectral_data.get('energy_rms')
        
        enhanced_transitions.append(trans)
    
    return enhanced_transitions


# ============================================================================
# CLI: View & Manage Cache
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Spectral Analysis Cache Manager")
    parser.add_argument('--stats', action='store_true', help="Show cache statistics")
    parser.add_argument('--clear', action='store_true', help="Clear entire cache (WARNING!)")
    parser.add_argument('--analyze', metavar='FILE', help="Analyze a single file")
    parser.add_argument('--bpm', type=float, default=120, help="BPM for analysis")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    mgr = SpectralCacheManager()
    
    if args.stats:
        stats = mgr.get_cache_stats()
        print(f"\n{'='*60}")
        print("📊 SPECTRAL ANALYSIS CACHE STATS")
        print(f"{'='*60}")
        print(f"  Cached tracks: {stats['cached_tracks']}")
        print(f"  Total duration: {stats['total_duration_hours']} hours")
        print(f"  Cache location: {stats['cache_path']}")
        print(f"{'='*60}\n")
    
    elif args.clear:
        response = input("⚠️  Really clear entire cache? (yes/no): ")
        if response.lower() == 'yes':
            mgr.clear_cache()
            print("✅ Cache cleared")
    
    elif args.analyze:
        print(f"\n🔍 Analyzing: {args.analyze} @ {args.bpm} BPM")
        result = mgr.get_or_analyze(args.analyze, args.bpm)
        if result:
            print("\n✅ Analysis complete:")
            for key, value in result.items():
                if value is not None:
                    print(f"  {key}: {value}")
        else:
            print("❌ Analysis failed")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
