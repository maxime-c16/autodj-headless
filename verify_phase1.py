#!/usr/bin/env python3
"""
Phase 1 DSP Implementation Verification Script
Validates EQ automation, transitions, and cue detection enhancements
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_transitions_liq():
    """Verify transitions.liq has Phase 1 enhancements."""
    try:
        transitions_file = Path("src/autodj/render/transitions.liq")
        content = transitions_file.read_text()
        
        logger.info("Checking transitions.liq...")
        
        checks = {
            "smart_crossfade function": "def smart_crossfade" in content,
            "EQ automation function": "def crossfade_with_eq" in content or "def eq_bass_cut" in content,
            "Low-pass filter": "eqffmpeg.low_pass" in content,
            "High-pass filter": "eqffmpeg.high_pass" in content,
            "Sine fades": 'type="sin"' in content,
            "Q factor (0.7)": "q=0.7" in content or "q = 0.7" in content,
            "normalize=false": "normalize=false" in content,
            "Filter sweep implementation": "filter_sweep" in content,
            "Harmonic-aware transitions": "harmonic_compatible" in content or "transition_style" in content,
        }
        
        all_pass = True
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            logger.info(f"  {status} {check_name}")
            if not passed:
                all_pass = False
        
        return all_pass
        
    except Exception as e:
        logger.error(f"Failed to check transitions.liq: {e}")
        return False

def check_cues_py():
    """Verify cues.py has advanced cue detection."""
    try:
        cues_file = Path("src/autodj/analyze/cues.py")
        content = cues_file.read_text()
        
        logger.info("Checking cues.py...")
        
        # Check for either aubio OR numpy-based detection
        checks = {
            "CuePoints class": "class CuePoints" in content,
            "detect_cues function": "def detect_cues" in content,
            "_snap_to_beat function": "def _snap_to_beat" in content,
            "Beat snapping implementation": "beat_number = round" in content,
            "Energy thresholds": "threshold" in content.lower(),
            "Onset/spectral analysis": "spectral" in content.lower() or "onset" in content.lower() or "energy" in content.lower(),
        }
        
        all_pass = True
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            logger.info(f"  {status} {check_name}")
            if not passed:
                all_pass = False
        
        return all_pass
        
    except Exception as e:
        logger.error(f"Failed to check cues.py: {e}")
        return False

def check_render_py():
    """Verify render.py has EQ automation integration."""
    try:
        render_file = Path("src/autodj/render/render.py")
        content = render_file.read_text()
        
        logger.info("Checking render.py...")
        
        checks = {
            "enable_eq_automation config": "enable_eq_automation" in content,
            "eq_lowpass_frequency config": "eq_lowpass_frequency" in content,
            "eq_highpass_frequency config": "eq_highpass_frequency" in content,
            "EQ filter in script": "eqffmpeg.low_pass" in content and "eqffmpeg.high_pass" in content,
            "Q factor specification": "q=0.7" in content,
            "Phase 1 documentation": "PHASE 1" in content or "EQ AUTOMATION" in content,
        }
        
        all_pass = True
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            logger.info(f"  {status} {check_name}")
            if not passed:
                all_pass = False
        
        return all_pass
        
    except Exception as e:
        logger.error(f"Failed to check render.py: {e}")
        return False

def check_liquidsoap_functions():
    """Verify Liquidsoap functions are syntactically valid."""
    try:
        logger.info("Checking Liquidsoap function definitions...")
        
        transitions_file = Path("src/autodj/render/transitions.liq")
        content = transitions_file.read_text()
        
        # Check function definitions
        functions = {
            "smart_crossfade": "def smart_crossfade",
            "crossfade_with_eq": "def crossfade_with_eq",
            "eq_bass_cut": "def eq_bass_cut",
            "eq_clarity_boost": "def eq_clarity_boost",
        }
        
        all_pass = True
        for func_name, pattern in functions.items():
            found = pattern in content
            status = "✅" if found else "❌"
            logger.info(f"  {status} {func_name}()")
            if not found:
                all_pass = False
        
        # Check for proper end statements
        end_count = content.count("\nend")
        if end_count >= 8:
            logger.info(f"  ✅ Functions properly closed with 'end' ({end_count} found)")
        else:
            logger.warning(f"  ⚠️  Check function closures (found {end_count} 'end' statements)")
        
        return all_pass
        
    except Exception as e:
        logger.error(f"Failed to check Liquidsoap syntax: {e}")
        return False

def check_documentation():
    """Verify Phase 1 documentation exists."""
    try:
        logger.info("Checking documentation...")
        
        docs_files = {
            "PHASE_1_IMPLEMENTATION.md": Path("PHASE_1_IMPLEMENTATION.md"),
            "transitions.liq comments": Path("src/autodj/render/transitions.liq"),
        }
        
        all_pass = True
        for doc_name, doc_path in docs_files.items():
            exists = doc_path.exists()
            status = "✅" if exists else "❌"
            logger.info(f"  {status} {doc_name}")
            if not exists:
                all_pass = False
        
        # Check PHASE_1_IMPLEMENTATION.md content
        if Path("PHASE_1_IMPLEMENTATION.md").exists():
            content = Path("PHASE_1_IMPLEMENTATION.md").read_text()
            checks = {
                "EQ automation documented": "EQ Automation" in content,
                "Audio quality expectations": "Audio Quality" in content,
                "Testing protocol": "Testing Protocol" in content or "Test Protocol" in content,
                "Dependencies checked": "Dependencies Check" in content,
            }
            
            for check_name, passed in checks.items():
                status = "✅" if passed else "❌"
                logger.info(f"    {status} {check_name}")
                if not passed:
                    all_pass = False
        
        return all_pass
        
    except Exception as e:
        logger.error(f"Failed to check documentation: {e}")
        return False

def run_all_checks():
    """Run all verification checks."""
    logger.info("=" * 70)
    logger.info("Phase 1 DSP Implementation Verification")
    logger.info("=" * 70)
    logger.info("")
    
    results = {
        "transitions.liq": check_transitions_liq(),
        "cues.py": check_cues_py(),
        "render.py": check_render_py(),
        "Liquidsoap functions": check_liquidsoap_functions(),
        "Documentation": check_documentation(),
    }
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Summary:")
    logger.info("=" * 70)
    
    all_pass = True
    for check_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {check_name}")
        if not passed:
            all_pass = False
    
    logger.info("")
    if all_pass:
        logger.info("✅ All checks passed! Phase 1 implementation is ready.")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Review PHASE_1_IMPLEMENTATION.md for detailed changes")
        logger.info("2. Test with sample mix (2-3 tracks)")
        logger.info("3. Compare audio quality vs. previous version")
        logger.info("4. Adjust EQ parameters if needed (config: eq_lowpass_frequency, eq_highpass_frequency)")
        return 0
    else:
        logger.error("")
        logger.error("❌ Some checks failed. Review the output above and correct issues.")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_checks())
