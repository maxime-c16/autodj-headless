"""
Comprehensive logging system for DJ EQ pipeline debugging.

Provides detailed logging at each stage:
- Track analysis (beat detection, drop detection)
- EQ skill generation (confidence scores, filter parameters)
- Filter calculations (DSP details: frequencies, magnitudes, Q factors)
- Annotation metadata (what was stored)
- Rendering progress (Liquidsoap execution, timing)
- Final validation (output verification)

All logs are structured and searchable for easy debugging.
"""

import logging
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional


class DetailedDJEQFormatter(logging.Formatter):
    """Custom formatter for DJ EQ debugging with color and structure."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[41m',   # Red background
        'RESET': '\033[0m',
    }
    
    def format(self, record):
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        
        # Format with timestamp
        return super().format(record)


class DJEQDebugLogger:
    """Comprehensive DJ EQ debugging logger with structured output."""
    
    def __init__(self, name: str, log_dir: Path):
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Main logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Create handlers
        timestamp = datetime.utcnow().isoformat().replace(':', '-')
        
        # 1. Console handler (INFO and above)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = DetailedDJEQFormatter(
            '[%(levelname)s] [%(name)s] %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # 2. Full debug file (everything)
        self.debug_file = self.log_dir / f'dj-eq-debug-{timestamp}.log'
        debug_handler = logging.FileHandler(self.debug_file)
        debug_handler.setLevel(logging.DEBUG)
        debug_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s'
        )
        debug_handler.setFormatter(debug_formatter)
        self.logger.addHandler(debug_handler)
        
        # 3. Analysis file (only analysis-related logs)
        self.analysis_file = self.log_dir / f'dj-eq-analysis-{timestamp}.log'
        self.analysis_handler = logging.FileHandler(self.analysis_file)
        self.analysis_handler.setLevel(logging.DEBUG)
        self.analysis_handler.setFormatter(debug_formatter)
        
        # 4. Filters file (only filter-related logs)
        self.filters_file = self.log_dir / f'dj-eq-filters-{timestamp}.log'
        self.filters_handler = logging.FileHandler(self.filters_file)
        self.filters_handler.setLevel(logging.DEBUG)
        self.filters_handler.setFormatter(debug_formatter)
        
        # JSON output for structured analysis
        self.json_file = self.log_dir / f'dj-eq-analysis-{timestamp}.jsonl'
        self.json_entries: List[Dict[str, Any]] = []
        
        self.logger.info(f"🎛️ DJ EQ Logger initialized")
        self.logger.info(f"   Debug log: {self.debug_file}")
        self.logger.info(f"   Analysis log: {self.analysis_file}")
        self.logger.info(f"   Filters log: {self.filters_file}")
        self.logger.info(f"   JSON output: {self.json_file}")
    
    # ===== PHASE 1: TRACK ANALYSIS =====
    
    def log_track_analysis_start(self, track_id: str, file_path: str, duration: float):
        """Log start of track analysis."""
        msg = f"🔍 ANALYZING TRACK: {track_id}"
        self.logger.info(msg)
        self.logger.debug(f"   File: {file_path}")
        self.logger.debug(f"   Duration: {duration:.2f}s")
        
        self._add_analysis_entry({
            'phase': 'track_analysis_start',
            'track_id': track_id,
            'file_path': file_path,
            'duration': duration,
        })
    
    def log_beat_detection(self, track_id: str, bpm: float, beat_times: List[float],
                          confidence: float = 0.0):
        """Log beat detection results."""
        self.logger.info(f"   ✅ Beat detection: {bpm:.1f} BPM ({len(beat_times)} beats)")
        self.logger.debug(f"      Confidence: {confidence:.2%}")
        self.logger.debug(f"      Sample beat times: {beat_times[:3] if beat_times else 'N/A'}")
        
        self._add_analysis_entry({
            'phase': 'beat_detection',
            'track_id': track_id,
            'bpm': bpm,
            'beat_count': len(beat_times),
            'confidence': confidence,
        })
    
    def log_drop_detection(self, track_id: str, drops: List[Dict[str, Any]]):
        """Log musical drop/section detection."""
        self.logger.info(f"   ✅ Drop detection: {len(drops)} drops found")
        for idx, drop in enumerate(drops):
            time = drop.get('time', 0)
            energy = drop.get('energy', 0)
            confidence = drop.get('confidence', 0)
            self.logger.debug(f"      Drop {idx}: {time:.2f}s (energy: {energy:.2f}, conf: {confidence:.2%})")
        
        self._add_analysis_entry({
            'phase': 'drop_detection',
            'track_id': track_id,
            'drop_count': len(drops),
            'drops': drops,
        })
    
    def log_energy_profile(self, track_id: str, energy_min: float, energy_max: float,
                          energy_mean: float, segments: int):
        """Log energy profile analysis."""
        self.logger.debug(f"   📊 Energy profile: min={energy_min:.2f}, max={energy_max:.2f}, mean={energy_mean:.2f}")
        self.logger.debug(f"      Analyzed in {segments} segments")
        
        self._add_analysis_entry({
            'phase': 'energy_profile',
            'track_id': track_id,
            'energy_min': energy_min,
            'energy_max': energy_max,
            'energy_mean': energy_mean,
            'segments': segments,
        })
    
    # ===== PHASE 2: DJ SKILL GENERATION =====
    
    def log_dj_skill_generation_start(self, track_id: str, bpm: float, drops_count: int):
        """Log start of DJ skill generation."""
        self.logger.info(f"🎚️  GENERATING DJ SKILLS: {track_id}")
        self.logger.debug(f"   BPM: {bpm:.1f}, Drops: {drops_count}")
    
    def log_dj_skill_opportunity(self, track_id: str, skill_idx: int, skill_type: str,
                                time: float, confidence: float, details: Dict[str, Any]):
        """Log individual DJ skill opportunity detected."""
        self.logger.debug(f"   🎯 Skill {skill_idx}: {skill_type} @ {time:.2f}s (conf: {confidence:.2%})")
        self.logger.debug(f"      Details: {details}")
    
    def log_dj_skill_filtered(self, track_id: str, reason: str, skill_type: str,
                             confidence: float, min_confidence: float):
        """Log DJ skill that was filtered out."""
        self.logger.debug(f"   ⏭️  Skipped: {skill_type} (conf: {confidence:.2%} < min: {min_confidence:.2%}) - {reason}")
    
    def log_dj_skills_generated(self, track_id: str, total_skills: int,
                               by_type: Dict[str, int], total_confidence_avg: float):
        """Log summary of generated DJ skills."""
        self.logger.info(f"   ✅ Generated {total_skills} DJ skills (avg confidence: {total_confidence_avg:.2%})")
        for skill_type, count in by_type.items():
            self.logger.debug(f"      {skill_type}: {count}")
        
        self._add_analysis_entry({
            'phase': 'dj_skills_generated',
            'track_id': track_id,
            'total_skills': total_skills,
            'by_type': by_type,
            'avg_confidence': total_confidence_avg,
        })
    
    # ===== PHASE 3: FILTER CALCULATIONS =====
    
    def log_filter_calculation_start(self, track_id: str, skill_idx: int, skill_type: str,
                                    time: float):
        """Log start of filter calculation."""
        self.logger.info(f"🔧 FILTER CALC: {track_id} Skill#{skill_idx} [{skill_type}] @ {time:.2f}s")
    
    def log_rbj_peaking_filter(self, track_id: str, skill_idx: int,
                              freq: float, mag_db: float, q: float,
                              b0: float, b1: float, b2: float,
                              a0: float, a1: float, a2: float):
        """Log RBJ peaking filter coefficients."""
        self.logger.info(f"   📊 RBJ Peaking Filter:")
        self.logger.info(f"      Frequency: {freq:.1f} Hz")
        self.logger.info(f"      Magnitude: {mag_db:.2f} dB")
        self.logger.info(f"      Q: {q:.4f}")
        self.logger.debug(f"      Numerator: b0={b0:.8f}, b1={b1:.8f}, b2={b2:.8f}")
        self.logger.debug(f"      Denominator: a0={a0:.8f}, a1={a1:.8f}, a2={a2:.8f}")
        
        self._log_to_filters_file(f"Track: {track_id}, Skill: {skill_idx}")
        self._log_to_filters_file(f"  Peaking Filter: {freq:.1f}Hz @ {mag_db:.2f}dB (Q={q:.4f})")
        self._log_to_filters_file(f"  b=[{b0:.8f}, {b1:.8f}, {b2:.8f}]")
        self._log_to_filters_file(f"  a=[{a0:.8f}, {a1:.8f}, {a2:.8f}]")
        self._log_to_filters_file("")
    
    def log_filter_envelope(self, track_id: str, skill_idx: int,
                           attack_time: float, release_time: float,
                           is_instant_release: bool):
        """Log filter envelope (attack/release)."""
        self.logger.debug(f"   🔔 Envelope:")
        self.logger.debug(f"      Attack: {attack_time:.4f}s")
        self.logger.debug(f"      Release: {release_time:.4f}s (instant={is_instant_release})")
    
    def log_filter_timing(self, track_id: str, skill_idx: int,
                         start_bar: int, start_sample: int,
                         duration_bars: int, duration_samples: int):
        """Log filter timing (bar-aligned)."""
        self.logger.debug(f"   ⏱️  Timing:")
        self.logger.debug(f"      Start: bar {start_bar} (sample {start_sample})")
        self.logger.debug(f"      Duration: {duration_bars} bars ({duration_samples} samples)")
    
    def log_filter_stability_check(self, track_id: str, skill_idx: int,
                                  is_stable: bool, pole_magnitude_max: float):
        """Log filter stability verification (important for DSP!)."""
        status = "✅ STABLE" if is_stable else "❌ UNSTABLE"
        self.logger.info(f"   {status} - Max pole magnitude: {pole_magnitude_max:.6f}")
        if not is_stable:
            self.logger.error(f"      WARNING: Filter may be unstable!")
    
    # ===== PHASE 4: ANNOTATION & STORAGE =====
    
    def log_annotation_storage(self, track_id: str, total_skills: int,
                              metadata: Dict[str, Any]):
        """Log that annotation was stored in transitions."""
        self.logger.info(f"📌 ANNOTATION STORED: {track_id}")
        self.logger.info(f"   Skills: {total_skills}")
        self.logger.debug(f"   Metadata keys: {list(metadata.keys())}")
        
        self._add_analysis_entry({
            'phase': 'annotation_stored',
            'track_id': track_id,
            'total_skills': total_skills,
            'metadata_keys': list(metadata.keys()),
        })
    
    # ===== PHASE 5: RENDERING =====
    
    def log_rendering_start(self, output_path: str, num_tracks: int):
        """Log start of rendering phase."""
        self.logger.info(f"🎬 RENDERING START")
        self.logger.info(f"   Output: {output_path}")
        self.logger.info(f"   Tracks: {num_tracks}")
    
    def log_liquidsoap_command(self, script_path: str, script_size: int):
        """Log Liquidsoap script being executed."""
        self.logger.debug(f"📜 Liquidsoap script:")
        self.logger.debug(f"   Path: {script_path}")
        self.logger.debug(f"   Size: {script_size} bytes")
    
    def log_liquidsoap_output(self, line: str, level: str = 'debug'):
        """Log Liquidsoap output line."""
        # Filter important lines
        if any(keyword in line.lower() for keyword in ['error', 'warning', 'fail', 'fatal']):
            self.logger.warning(f"   [liquidsoap] {line}")
        elif any(keyword in line.lower() for keyword in ['complete', 'success', 'done']):
            self.logger.info(f"   [liquidsoap] {line}")
        else:
            self.logger.debug(f"   [liquidsoap] {line}")
    
    def log_rendering_complete(self, output_path: str, file_size_mb: float, duration_sec: float):
        """Log successful rendering completion."""
        self.logger.info(f"✅ RENDERING COMPLETE")
        self.logger.info(f"   File: {output_path}")
        self.logger.info(f"   Size: {file_size_mb:.1f} MB")
        self.logger.info(f"   Duration: {duration_sec:.1f}s")
    
    # ===== PHASE 6: VALIDATION =====
    
    def log_validation_start(self, output_path: str):
        """Log start of output validation."""
        self.logger.info(f"✔️  VALIDATING OUTPUT")
        self.logger.debug(f"   File: {output_path}")
    
    def log_validation_check(self, check_name: str, passed: bool, details: str = ""):
        """Log individual validation check."""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.logger.info(f"   {status}: {check_name}")
        if details:
            self.logger.debug(f"      {details}")
    
    def log_validation_complete(self, passed: bool, checks_total: int, checks_passed: int):
        """Log validation completion."""
        status = "✅ VALID" if passed else "❌ INVALID"
        self.logger.info(f"{status} - {checks_passed}/{checks_total} checks passed")
    
    # ===== DEBUGGING & SUPPORT =====
    
    def log_error_with_context(self, error_msg: str, track_id: Optional[str] = None,
                              skill_idx: Optional[int] = None,
                              context: Optional[Dict[str, Any]] = None):
        """Log error with full context for debugging."""
        self.logger.error(f"❌ ERROR: {error_msg}")
        if track_id:
            self.logger.error(f"   Track: {track_id}")
        if skill_idx is not None:
            self.logger.error(f"   Skill: {skill_idx}")
        if context:
            self.logger.error(f"   Context:")
            for key, val in context.items():
                self.logger.error(f"      {key}: {val}")
    
    def log_performance_metrics(self, phase: str, duration_sec: float, 
                               tracks_processed: int, skills_generated: int):
        """Log performance metrics for optimization."""
        rate = tracks_processed / duration_sec if duration_sec > 0 else 0
        self.logger.info(f"⚡ PERFORMANCE [{phase}]")
        self.logger.info(f"   Duration: {duration_sec:.2f}s")
        self.logger.info(f"   Tracks: {tracks_processed}")
        self.logger.info(f"   Skills: {skills_generated}")
        self.logger.info(f"   Rate: {rate:.2f} tracks/sec")
    
    # ===== INTERNAL HELPERS =====
    
    def _add_analysis_entry(self, entry: Dict[str, Any]):
        """Add structured entry to JSON output."""
        entry['timestamp'] = datetime.utcnow().isoformat()
        self.json_entries.append(entry)
    
    def _log_to_filters_file(self, message: str):
        """Log to filters-specific file."""
        filters_logger = logging.getLogger(f"{self.name}.filters")
        filters_logger.addHandler(self.filters_handler)
        filters_logger.info(message)
    
    def save_json_analysis(self):
        """Save all structured analysis entries to JSON file."""
        with open(self.json_file, 'w') as f:
            for entry in self.json_entries:
                f.write(json.dumps(entry) + '\n')
        self.logger.info(f"💾 Analysis saved: {self.json_file}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of logged activities."""
        return {
            'debug_log': str(self.debug_file),
            'analysis_log': str(self.analysis_file),
            'filters_log': str(self.filters_file),
            'json_output': str(self.json_file),
            'entries': len(self.json_entries),
        }


def create_nightly_logger(log_dir: Path = None) -> DJEQDebugLogger:
    """Factory function to create logger for nightly runs.
    
    If log_dir is not provided, uses AUTODJ_LOG_DIR environment variable
    or defaults to /tmp/autodj-logs (accessible from Docker).
    
    ⚠️ IMPORTANT: Docker cannot write to /home/mcauchy!
    Always use /tmp or /app/data/logs for container compatibility.
    """
    import os
    if log_dir is None:
        # Try environment variable first, then fallback to /tmp/autodj-logs
        log_dir = os.environ.get('AUTODJ_LOG_DIR', None)
        if log_dir is None:
            # Prefer /app/data/logs if inside container, else /tmp/autodj-logs
            if os.path.exists('/app/data'):
                log_dir = '/app/data/logs'
            else:
                log_dir = '/tmp/autodj-logs'
        log_dir = Path(log_dir)
    return DJEQDebugLogger('autodj.nightly.dj_eq', log_dir)
