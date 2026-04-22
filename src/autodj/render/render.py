"""
Liquidsoap Render Engine.

Generates and executes Liquidsoap offline mixing scripts.
Per SPEC.md § 5.3:
- Offline clock
- Streaming decode/encode
- Memory-bounded
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, List, Dict
import json
from datetime import datetime
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
import os
import threading
import time
import shutil
from subprocess import PIPE, STDOUT, Popen

from autodj.render.segmenter import RenderSegmenter, SegmentPlan
from autodj.render.loop_extract import (
    create_loop_hold,
    create_loop_roll,
    create_temp_loop_dir,
    cleanup_temp_loops,
)
from autodj.render.eq_liquidsoap import EQLiquidsoap
from autodj.render.eq_automation import EQAutomationEngine
from autodj.generate.aggressive_eq_annotator import AggressiveDJEQAnnotator
from autodj.debug.dj_eq_logger import create_nightly_logger
from autodj.render.segment_eq_strategies import apply_segment_eq

# Initialize logger early (before imports that may fail)
logger = logging.getLogger(__name__)
debug_logger = None  # Will be initialized if EQ is enabled

# DJ Techniques Integration
try:
    from autodj.render.dj_techniques_render import DJTechniquesRenderer, create_listening_guide
    DJ_TECHNIQUES_AVAILABLE = True
except ImportError:
    DJ_TECHNIQUES_AVAILABLE = False
    logger.info("ℹ️ DJ Techniques rendering not available")

# PHASE 2: Phase 0 Precision Fixes Integration
try:
    from autodj.analyze.confidence_validator import ConfidenceValidator, create_confidence_validator
    from autodj.analyze.bpm_multipass_validator import BPMMultiPassValidator, create_multipass_validator
    from autodj.analyze.grid_validator import GridValidator, create_grid_validator
    PHASE_0_VALIDATORS_AVAILABLE = True
except ImportError:
    PHASE_0_VALIDATORS_AVAILABLE = False
    logger.warning("⚠️ Phase 0 validators not available - precision fixes disabled")

# PHASE 5: Micro-Techniques Integration
try:
    from autodj.render.phase5_integration import Phase5Renderer
    from autodj.render.phase5_micro_techniques import MicroTechniqueDatabase
    from autodj.generate.personas import DJPersona, get_persona_config
    PHASE_5_AVAILABLE = True
except ImportError:
    PHASE_5_AVAILABLE = False
    logger.warning("⚠️ Phase 5 micro-techniques not available - advanced mixing disabled")

# PHASE 1: Early Transitions Integration
try:
    from autodj.render.phases import Phase1EarlyTransitions, Phase1Config, EarlyTransitionModel
    PHASE_1_AVAILABLE = True
except ImportError:
    PHASE_1_AVAILABLE = False
    logger.warning("⚠️ Phase 1 early transitions not available - professional DJ timing disabled")

# PHASE 5: Liquidsoap Script Injection for Micro-Techniques
try:
    from autodj.render.phase5_script_injection import (
        generate_phase5_track_effects,
        validate_liquidsoap_syntax,
        inject_phase5_into_script,
    )
    PHASE_5_INJECTION_AVAILABLE = True
except ImportError:
    PHASE_5_INJECTION_AVAILABLE = False
    logger.warning("⚠️ Phase 5 Liquidsoap injection not available - micro-techniques will not be rendered")


# ============================================================================
# PHASE 2: PHASE 0 PRECISION FIXES VALIDATION
# ============================================================================

def apply_phase0_precision_fixes(
    transitions: list,
    config: dict,
    precision_fixes_enabled: bool = True,
    confidence_validator_enabled: bool = True,
    bpm_multipass_enabled: bool = True,
    grid_validation_enabled: bool = True,
) -> tuple:
    """
    Apply Phase 0 precision validators to transitions.
    
    Validates and potentially corrects:
    - BPM confidence (graduated 3-tier system)
    - BPM detection (3-pass voting with octave error detection)
    - Grid fitness (4-check validation framework)
    
    Args:
        transitions: List of transition dicts with BPM/grid data
        config: Render config dict
        precision_fixes_enabled: Master switch for all precision fixes
        confidence_validator_enabled: Enable confidence tier validation
        bpm_multipass_enabled: Enable multi-pass BPM validation
        grid_validation_enabled: Enable grid fitness validation
        
    Returns:
        (validated_transitions, metrics_summary)
    """
    if not precision_fixes_enabled or not PHASE_0_VALIDATORS_AVAILABLE:
        logger.debug("Phase 0 precision fixes disabled or unavailable")
        return transitions, {}
    
    logger.info("🔬 PHASE 0: Applying precision fixes to transitions...")
    
    # Initialize validators
    validators_created = {}
    metrics = {
        'total_transitions': len(transitions),
        'confidence_validations': 0,
        'bpm_multipass_validations': 0,
        'grid_validations': 0,
        'high_confidence_count': 0,
        'medium_confidence_count': 0,
        'low_confidence_count': 0,
    }
    
    try:
        if confidence_validator_enabled:
            conf_config = {
                'confidence_high_threshold': config.get('confidence_high_threshold', 0.90),
                'confidence_medium_threshold': config.get('confidence_medium_threshold', 0.70),
                'enable_logging': True,
            }
            confidence_val = create_confidence_validator(conf_config)
            validators_created['confidence'] = confidence_val
            logger.debug(f"✅ Confidence validator created (HIGH: {conf_config['confidence_high_threshold']}, MEDIUM: {conf_config['confidence_medium_threshold']})")
    except Exception as e:
        logger.warning(f"⚠️ Confidence validator failed: {e}")
    
    try:
        if bpm_multipass_enabled:
            bpm_config = {
                'bpm_search_range': config.get('bpm_search_range', [50, 200]),
            }
            bpm_validator = create_multipass_validator(bpm_config)
            validators_created['bpm_multipass'] = bpm_validator
            logger.debug(f"✅ BPM multi-pass validator created")
    except Exception as e:
        logger.warning(f"⚠️ BPM multi-pass validator failed: {e}")
    
    try:
        if grid_validation_enabled:
            grid_config = {
                'grid_high_fitness_threshold': config.get('grid_high_fitness_threshold', 0.80),
                'grid_medium_fitness_threshold': config.get('grid_medium_fitness_threshold', 0.60),
            }
            grid_validator = create_grid_validator(grid_config)
            validators_created['grid'] = grid_validator
            logger.debug(f"✅ Grid validator created (HIGH: {grid_config['grid_high_fitness_threshold']}, MEDIUM: {grid_config['grid_medium_fitness_threshold']})")
    except Exception as e:
        logger.warning(f"⚠️ Grid validator failed: {e}")
    
    # Validate each transition
    for idx, trans in enumerate(transitions):
        trans_id = trans.get('track_id', f'track_{idx}')
        file_path = trans.get('file_path', '')
        
        # Confidence validation
        if 'confidence' in validators_created:
            bpm = trans.get('bpm', 0)
            bpm_confidence = trans.get('bpm_confidence', 0.5)
            
            try:
                result = validators_created['confidence'].validate_bpm_confidence(
                    bpm, bpm_confidence, detection_method=trans.get('bpm_method', 'unknown')
                )
                trans['_phase0_confidence_validation'] = {
                    'tier': result.tier.value,
                    'valid': result.valid,
                    'requires_validation': result.requires_validation,
                    'recommendation': result.recommendation,
                    'message': result.message,
                }
                metrics['confidence_validations'] += 1
                metrics[f'{result.tier.value}_confidence_count'] += 1
                logger.debug(f"  [{trans_id}] {result.message}")
            except Exception as e:
                logger.warning(f"  [{trans_id}] Confidence validation failed: {e}")
        
        # BPM multi-pass validation
        if 'bpm_multipass' in validators_created and file_path:
            try:
                import time
                start = time.time()
                result = validators_created['bpm_multipass'].validate_bpm_multipass(
                    file_path,
                    config,
                    trans.get('bpm', 0),
                    trans.get('bpm_confidence', 0.5),
                    trans.get('bpm_method', 'unknown')
                )
                elapsed = time.time() - start
                
                trans['_phase0_bpm_multipass'] = {
                    'final_bpm': result.bpm,
                    'final_confidence': result.confidence,
                    'agreement_level': result.agreement_level,
                    'octave_error_detected': result.octave_error_detected,
                    'octave_error_type': result.octave_error_type,
                    'octave_corrected_bpm': result.octave_corrected_bpm,
                    'votes': result.votes,
                    'detection_time_sec': elapsed,
                }
                
                # Update transition BPM if octave error was corrected
                if result.octave_error_detected and result.octave_corrected_bpm:
                    trans['bpm'] = result.octave_corrected_bpm
                    trans['bpm_confidence'] = result.confidence
                    logger.warning(f"  [{trans_id}] Octave error corrected: {result.octave_error_type} ({result.octave_corrected_bpm:.1f} BPM)")
                
                metrics['bpm_multipass_validations'] += 1
                logger.debug(f"  [{trans_id}] Agreement: {result.agreement_level}, Confidence: {result.confidence:.2f}")
            except Exception as e:
                logger.warning(f"  [{trans_id}] BPM multipass validation failed: {e}")
        
        # Grid validation
        if 'grid' in validators_created and file_path:
            try:
                import time
                start = time.time()
                
                # Load audio for grid validation
                import librosa
                audio, sr = librosa.load(file_path, sr=44100, mono=True)
                downbeat_sample = trans.get('downbeat_sample', 0)
                
                result = validators_created['grid'].validate_grid(
                    audio, sr,
                    trans.get('bpm', 0),
                    int(downbeat_sample),
                    secondary_bpm=trans.get('_phase0_bpm_multipass', {}).get('final_bpm')
                )
                elapsed = time.time() - start
                
                trans['_phase0_grid_validation'] = {
                    'fitness_score': result.fitness_score,
                    'confidence': result.confidence.value,
                    'recommendation': result.recommendation,
                    'onset_alignment': result.onset_alignment_percent,
                    'tempo_consistency_bpm_variance': result.tempo_consistency_bpm_variance,
                    'phase_alignment_offset_ms': result.phase_alignment_offset_ms,
                    'spectral_bpm_agreement': result.spectral_bpm_agreement,
                    'validation_time_sec': elapsed,
                }
                
                metrics['grid_validations'] += 1
                logger.debug(f"  [{trans_id}] Grid fitness: {result.fitness_score:.2f} ({result.confidence.value})")
            except Exception as e:
                logger.debug(f"  [{trans_id}] Grid validation not available: {e}")
    
    logger.info(f"🔬 Phase 0 precision fixes applied:")
    logger.info(f"  - Confidence validations: {metrics['confidence_validations']}/{metrics['total_transitions']}")
    logger.info(f"  - BPM multipass validations: {metrics['bpm_multipass_validations']}/{metrics['total_transitions']}")
    logger.info(f"  - Grid validations: {metrics['grid_validations']}/{metrics['total_transitions']}")
    if metrics['high_confidence_count'] > 0:
        logger.info(f"  - High confidence: {metrics['high_confidence_count']} ({metrics['high_confidence_count']/metrics['total_transitions']*100:.1f}%)")
    if metrics['medium_confidence_count'] > 0:
        logger.info(f"  - Medium confidence: {metrics['medium_confidence_count']} ({metrics['medium_confidence_count']/metrics['total_transitions']*100:.1f}%)")
    if metrics['low_confidence_count'] > 0:
        logger.info(f"  - Low confidence: {metrics['low_confidence_count']} ({metrics['low_confidence_count']/metrics['total_transitions']*100:.1f}%)")
    
    return transitions, metrics


# ============================================================================
# PHASE 5: MICRO-TECHNIQUES INTEGRATION
# ============================================================================

def apply_phase5_micro_techniques(
    transitions: list,
    config: dict,
    persona: Optional[str] = None,
    seed: Optional[int] = None,
) -> tuple:
    """
    Apply Phase 5 micro-techniques to transitions.
    
    Selects and integrates DJ micro-techniques (stutter rolls, bass cuts, etc.)
    into the transition data for rendering.
    
    Args:
        transitions: List of transition dicts
        config: Render config
        persona: DJ Persona name ("tech_house", "high_energy", "minimal", "acid")
        seed: Random seed for deterministic selection
    
    Returns:
        Tuple of (updated_transitions, phase5_metrics)
    """
    if not PHASE_5_AVAILABLE:
        logger.warning("⚠️ Phase 5 not available - skipping micro-techniques")
        return transitions, {}
    
    try:
        logger.info("=" * 70)
        logger.info("🎵 PHASE 5: MICRO-TECHNIQUES SELECTION & INTEGRATION")
        logger.info("=" * 70)
        
        # Initialize Phase 5 renderer
        phase5_renderer = Phase5Renderer(seed=seed)
        
        # Get persona preferences if specified
        preferred_techniques = None
        avoided_techniques = None
        persona_config = None
        
        if persona:
            try:
                persona_enum = DJPersona[persona.upper().replace("-", "_")]
                persona_config = get_persona_config(persona_enum)
                preferred_techniques = persona_config.preferred_techniques
                avoided_techniques = persona_config.avoid_techniques
                
                logger.info(f"🎭 Persona: {persona_config.name}")
                logger.info(f"   Preferred techniques: {len(preferred_techniques)}")
                logger.info(f"   Avoided techniques: {len(avoided_techniques)}")
            except (KeyError, ValueError):
                logger.warning(f"⚠️ Unknown persona: {persona}")
        
        # Process each transition
        total_techniques_selected = 0
        metrics = {
            'total_transitions': len(transitions),
            'transitions_with_techniques': 0,
            'total_techniques_selected': 0,
            'by_type': {},
            'persona': persona,
        }
        
        for idx, trans in enumerate(transitions):
            bpm = trans.get("target_bpm") or trans.get("bpm", 120.0)
            duration_sec = trans.get("duration_seconds", 30.0)
            
            # Calculate how many techniques to select (1 per ~16 bars)
            bars = (duration_sec / 60.0) * (bpm / 4.0)
            target_count = max(1, int(bars / 16))
            
            # Get persona spacing preferences
            min_interval = 8.0  # Default
            if persona_config:
                min_interval = float(persona_config.min_technique_interval_bars)
            
            # Select techniques for this transition
            selections = phase5_renderer.selector.select_techniques_for_section(
                section_bars=bars,
                target_technique_count=target_count,
                min_interval_bars=min_interval,
                preferred_types=preferred_techniques,
                avoided_types=avoided_techniques
            )
            
            if selections:
                # Store micro-techniques in transition metadata
                trans['phase5_micro_techniques'] = [
                    {
                        'type': sel.type.value,
                        'name': phase5_renderer.db.get_technique(sel.type).name,
                        'start_bar': sel.start_bar,
                        'duration_bars': sel.duration_bars,
                        'duration_seconds': sel.duration_bars * (60.0 / bpm) * 4.0,
                        'confidence': sel.confidence_score,
                        'parameters': sel.parameters,
                        'reason': sel.reason
                    }
                    for sel in selections
                ]
                
                metrics['transitions_with_techniques'] += 1
                metrics['total_techniques_selected'] += len(selections)
                
                # Track by type
                for sel in selections:
                    tech_name = phase5_renderer.db.get_technique(sel.type).name
                    if tech_name not in metrics['by_type']:
                        metrics['by_type'][tech_name] = 0
                    metrics['by_type'][tech_name] += 1
                
                logger.info(f"  [{idx}] {len(selections)} techniques @ {bpm:.0f} BPM")
                for sel in selections:
                    tech = phase5_renderer.db.get_technique(sel.type)
                    logger.info(f"      - {tech.name} @ bar {sel.start_bar:.1f}")
        
        # Log summary
        logger.info("")
        logger.info(f"🎵 Phase 5 Summary:")
        logger.info(f"  - Transitions with techniques: {metrics['transitions_with_techniques']}/{metrics['total_transitions']}")
        logger.info(f"  - Total techniques selected: {metrics['total_techniques_selected']}")
        if persona_config:
            logger.info(f"  - Persona: {persona_config.name}")
            logger.info(f"  - Energy build: {persona_config.energy_build}")
        
        logger.info("")
        for tech_name, count in sorted(metrics['by_type'].items(), key=lambda x: -x[1]):
            logger.info(f"  - {tech_name}: {count}")
        
        logger.info("=" * 70)
        
        return transitions, metrics
        
    except Exception as e:
        logger.error(f"❌ Phase 5 processing failed: {e}")
        return transitions, {'error': str(e)}


# ============================================================================
# PHASE 1: EARLY TRANSITIONS
# ============================================================================

def apply_phase1_early_transitions(
    transitions: list,
    outgoing_tracks: Dict[str, Dict],
    config: dict,
    phase1_enabled: bool = True,
    phase1_model: str = "fixed_16_bars",
) -> tuple:
    """
    Apply Phase 1 Early Transitions to transitions.
    
    Enables professional DJ-style mixing that starts 16-32 bars before
    the outgoing track's outro ends, rather than at track boundary.
    
    Args:
        transitions: List of transition dicts
        outgoing_tracks: Dict mapping track_id → track metadata (with outro detection)
        config: Render config
        phase1_enabled: Master switch for Phase 1
        phase1_model: Timing model ("fixed_16_bars", "fixed_24_bars", "fixed_32_bars", "adaptive")
    
    Returns:
        Tuple of (updated_transitions, phase1_metrics)
    """
    if not PHASE_1_AVAILABLE or not phase1_enabled:
        return transitions, {}
    
    try:
        logger.info("=" * 70)
        logger.info("🎵 PHASE 1: EARLY TRANSITIONS - PROFESSIONAL DJ TIMING")
        logger.info("=" * 70)
        
        # Convert model string to enum
        try:
            model = EarlyTransitionModel[phase1_model.upper().replace("-", "_")]
        except KeyError:
            logger.warning(f"⚠️ Unknown Phase 1 model: {phase1_model}, using FIXED_16_BARS")
            model = EarlyTransitionModel.FIXED_16_BARS
        
        # Create Phase 1 engine with config
        phase1_config = Phase1Config(
            enabled=True,
            model=model,
            fallback_bars=16,
            require_outro_detection=False,
            log_timing_details=True
        )
        
        engine = Phase1EarlyTransitions(phase1_config)
        
        logger.info(f"🎭 Phase 1 Model: {model.value}")
        logger.info(f"   Fallback bars: {phase1_config.fallback_bars}")
        logger.info("")
        
        # Apply Phase 1 to each transition
        transitions_updated = []
        metrics = {
            'total_transitions': len(transitions),
            'transitions_with_early_timing': 0,
            'outro_detected_count': 0,
            'average_early_start_seconds': 0,
            'timing_by_transition': [],
        }
        
        early_start_times = []
        
        for idx, trans in enumerate(transitions):
            track_id = trans.get('track_id', f'track_{idx}')
            outgoing_track = outgoing_tracks.get(track_id, {})
            
            # Get incoming track (next track)
            next_track_id = trans.get('next_track_id')
            incoming_track = {}
            if next_track_id and idx + 1 < len(transitions):
                incoming_track = outgoing_tracks.get(next_track_id, {})
            
            # Apply Phase 1 timing calculation
            modified_trans, metadata = engine.apply_to_transition(trans, outgoing_track, incoming_track)
            
            if metadata.enabled and metadata.crossfade_start_seconds is not None:
                # Store Phase 1 metadata in transition
                modified_trans['phase1_metadata'] = metadata.to_dict()
                
                metrics['transitions_with_early_timing'] += 1
                if metadata.outro_detected:
                    metrics['outro_detected_count'] += 1
                
                early_start_times.append(metadata.crossfade_start_seconds)
                
                logger.info(f"  [{idx}] {trans.get('title', 'Unknown')}")
                if metadata.outro_detected:
                    logger.info(f"      ✅ Outro detected @ {metadata.outro_start_seconds:.1f}s")
                else:
                    logger.info(f"      ℹ️ Outro not detected, using fallback")
                
                logger.info(f"      🔄 Early start @ {metadata.crossfade_start_seconds:.1f}s")
                logger.info(f"      ⏱️  {metadata.early_transition_bars} bars before outro")
                logger.info(f"      📊 {metadata.crossfade_duration_bars} bar crossfade @ {metadata.bpm:.0f} BPM")
                
                metrics['timing_by_transition'].append({
                    'index': idx,
                    'title': trans.get('title', ''),
                    'outro_start': metadata.outro_start_seconds,
                    'crossfade_start': metadata.crossfade_start_seconds,
                    'early_bars': metadata.early_transition_bars,
                    'bpm': metadata.bpm,
                })
            
            transitions_updated.append(modified_trans)
        
        # Calculate average early start time
        if early_start_times:
            metrics['average_early_start_seconds'] = sum(early_start_times) / len(early_start_times)
        
        # Summary
        logger.info("")
        logger.info(f"✅ Phase 1 Summary:")
        logger.info(f"  - Transitions with early timing: {metrics['transitions_with_early_timing']}/{metrics['total_transitions']}")
        logger.info(f"  - Outro detected: {metrics['outro_detected_count']}")
        logger.info(f"  - Average early start: {metrics['average_early_start_seconds']:.1f}s")
        logger.info(f"  - Timing model: {model.value}")
        logger.info("=" * 70)
        
        return transitions_updated, metrics
        
    except Exception as e:
        logger.error(f"❌ Phase 1 processing failed: {e}")
        import traceback
        traceback.print_exc()
        return transitions, {'error': str(e)}


def render(
    transitions_json_path: str,
    output_path: str,
    config: dict,
    timeout_seconds: Optional[int] = None,  # No timeout (None = unlimited)
    eq_enabled: bool = True,  # NEW: Enable DJ EQ automation
    eq_strategy: str = "ladspa",  # NEW: EQ strategy ("ladspa", "ffmpeg", "calf", "hybrid")
    precision_fixes_enabled: bool = True,  # PHASE 2: Enable Phase 0 precision fixes
    confidence_validator_enabled: bool = True,  # PHASE 2: Enable confidence validation
    bpm_multipass_enabled: bool = True,  # PHASE 2: Enable multi-pass BPM validation
    grid_validation_enabled: bool = True,  # PHASE 2: Enable grid fitness validation
    phase1_enabled: bool = True,  # PHASE 1: Enable early transitions
    phase1_model: str = "fixed_16_bars",  # PHASE 1: Timing model
    phase5_enabled: bool = True,  # PHASE 5: Enable micro-techniques
    persona: Optional[str] = None,  # PHASE 5: DJ Persona ("tech_house", "high_energy", "minimal", "acid")
) -> bool:
    """
    Execute Liquidsoap rendering.

    Args:
        transitions_json_path: Path to transitions.json
        output_path: Path to output mix file
        config: Render config dict
        timeout_seconds: Max runtime in seconds (None = no timeout)
        eq_enabled: Whether to enable DJ EQ automation (default: True)
        eq_strategy: Which EQ strategy ("ladspa", "ffmpeg", "calf", "hybrid")

    Returns:
        True if successful, False otherwise
    """
    script_path = None
    temp_loop_dir = None
    try:
        # Load transitions plan
        with open(transitions_json_path, "r") as f:
            plan = json.load(f)

        # Preflight: ensure each transition has a valid file path
        missing = []
        for idx, t in enumerate(plan.get("transitions", [])):
            fp = t.get("file_path")
            if not fp:
                missing.append((idx, fp, "missing path"))
                continue
            try:
                p = Path(fp)
                if not p.exists():
                    missing.append((idx, fp, "not found"))
            except Exception:
                missing.append((idx, fp, "invalid path"))

        if missing:
            logger.error("Preflight check failed: some tracks missing or unreadable")
            for m in missing:
                logger.error(f" Transition {m[0]}: {m[1]} -> {m[2]}")
            return False

        # Check if any transition uses v2 types (loop_hold, drop_swap, etc.)
        transitions = plan.get("transitions", [])
        
        # PHASE 2: Apply Phase 0 Precision Fixes
        if precision_fixes_enabled:
            logger.info("=" * 70)
            transitions, phase0_metrics = apply_phase0_precision_fixes(
                transitions,
                config,
                precision_fixes_enabled=precision_fixes_enabled,
                confidence_validator_enabled=confidence_validator_enabled,
                bpm_multipass_enabled=bpm_multipass_enabled,
                grid_validation_enabled=grid_validation_enabled,
            )
            # Save phase0 metrics to transition metadata
            plan['_phase0_metrics'] = phase0_metrics
            logger.info("=" * 70)
        
        # 🎛️ NEW: Aggressive DJ EQ Annotation (Beat-Synced EQ System)
        # Annotate each track with EQ opportunities before rendering
        if eq_enabled:
            try:
                global debug_logger
                debug_logger = create_nightly_logger()
                
                logger.info("🎛️ AGGRESSIVE DJ EQ: Annotating tracks with beat-synced opportunities...")
                debug_logger.log_rendering_start(output_path, len(transitions))
                
                annotator = AggressiveDJEQAnnotator(sr=44100, min_confidence=0.65)
                
                for idx, trans in enumerate(transitions):
                    file_path = trans.get("file_path", "")
                    track_id = trans.get("track_id", f"track_{idx}")
                    title = trans.get("title", f"Track {idx}")
                    
                    if not file_path or not Path(file_path).exists():
                        logger.warning(f"  ⚠️ Track {idx} not found, skipping EQ annotation")
                        debug_logger.log_error_with_context(
                            "Track file not found",
                            track_id=track_id,
                            context={'file_path': file_path, 'index': idx}
                        )
                        continue
                    
                    try:
                        # Log track analysis start
                        debug_logger.log_track_analysis_start(track_id, file_path, 0)
                        
                        # Create mock track analysis (would come from DB in production)
                        # For now, use empty analysis - annotator will detect from audio
                        track_analysis = {
                            'sections_json': json.dumps({'sections': []}),
                            'energy_profile_json': json.dumps({'values': []}),
                        }
                        
                        # Annotate and store in writable data directory (not NAS)
                        # Use /tmp for temporary annotations (works on both host and container)
                        annotation_data_dir = Path("/tmp/autodj_eq_annotations")
                        annotation_data_dir.mkdir(parents=True, exist_ok=True)
                        output_json = annotation_data_dir / f"eq_annotation_{track_id}.json"
                        success = annotator.annotate_track(file_path, track_analysis, str(output_json))
                        
                        if success:
                            # Load annotation and add to transition metadata
                            with open(output_json, 'r') as f:
                                annotation = json.load(f)
                            
                            trans['eq_annotation'] = annotation
                            eq_count = annotation.get('total_eq_skills', 0)
                            bpm = annotation.get('detected_bpm', 0)
                            
                            logger.info(f"  ✅ {title}: {eq_count} DJ skills @ {bpm:.1f} BPM")
                            debug_logger.log_annotation_storage(track_id, eq_count, annotation)
                            
                            # Log detailed skill breakdown
                            skills_by_type = annotation.get('skills_by_type', {})
                            debug_logger.log_dj_skills_generated(
                                track_id, eq_count,
                                by_type=skills_by_type if skills_by_type else {'total': eq_count},
                                total_confidence_avg=annotation.get('average_confidence', 0)
                            )
                        else:
                            logger.warning(f"  ⚠️ {title}: EQ annotation failed")
                            debug_logger.log_error_with_context(
                                "EQ annotation failed",
                                track_id=track_id,
                                context={'file_path': file_path}
                            )
                    
                    except Exception as e:
                        logger.warning(f"  ⚠️ {title}: EQ annotation error: {e}")
                        debug_logger.log_error_with_context(
                            f"EQ annotation exception: {e}",
                            track_id=track_id,
                            context={'file_path': file_path, 'error_type': type(e).__name__}
                        )
                        continue
                
                logger.info("🎛️ EQ annotation complete - ready for aggressive mix!")
                debug_logger.save_json_analysis()
                
                # Log summary
                summary = debug_logger.get_summary()
                logger.info(f"📊 Debug logs saved:")
                logger.info(f"   - {summary['debug_log']}")
                logger.info(f"   - {summary['analysis_log']}")
                logger.info(f"   - {summary['filters_log']}")
                
                # 💾 BUG FIX #2: Save updated transitions with EQ annotations back to JSON
                try:
                    with open(transitions_json_path, "w") as f:
                        json.dump(plan, f, indent=2)
                    logger.info(f"✅ Transitions JSON updated with {len(transitions)} EQ annotations")
                except Exception as e:
                    logger.error(f"❌ Failed to save transitions JSON with EQ annotations: {e}")
            
            except ImportError:
                logger.warning("⚠️ AggressiveDJEQAnnotator not available, skipping EQ annotation")
            except Exception as e:
                logger.warning(f"⚠️ EQ annotation failed: {e}")
                if debug_logger:
                    debug_logger.log_error_with_context(f"Annotation phase failed: {e}")
        
        has_v2_transitions = any(
            t.get("transition_type") in ("loop_hold", "drop_swap", "loop_roll", "eq_blend")
            for t in transitions
        )

        # 🎛️ NEW: Pre-process tracks with EQ before Liquidsoap mixing
        # DISABLED: Preprocessing causes scipy out-of-memory errors
        # SOLUTION: Use Liquidsoap-native filter blending instead
        if False and eq_enabled:  # Disabled for now
            logger.info("🎛️ EQ pre-processing DISABLED (using Liquidsoap native filters instead)...")
            logger.info(f"   EQ enabled: {eq_enabled}")
            logger.info(f"   Transitions JSON: {transitions_json_path}")
            try:
                from autodj.render.eq_preprocessor import preprocess_transitions
                temp_eq_dir = Path("/tmp/autodj_eq_processed")
                logger.info(f"   Output dir: {temp_eq_dir}")
                success = preprocess_transitions(transitions_json_path, temp_eq_dir, eq_enabled=True)
                if success:
                    logger.info(f"✅ EQ pre-processing complete, using processed tracks")
                else:
                    logger.warning(f"⚠️ EQ pre-processing failed, continuing with original tracks")
            except ImportError as e:
                logger.warning(f"⚠️ EQ preprocessor not available: {e}, skipping")
            except Exception as e:
                logger.warning(f"⚠️ EQ pre-processing error: {e}")
                import traceback
                traceback.print_exc()
        
        # 🎵 PHASE 1: Apply early transitions
        if phase1_enabled:
            # Build outgoing tracks dict for Phase 1 (need track metadata with outro info)
            outgoing_tracks = {}
            for trans in transitions:
                track_id = trans.get('track_id')
                if track_id:
                    # Extract track info from transition
                    outgoing_tracks[track_id] = {
                        'id': track_id,
                        'title': trans.get('title', ''),
                        'duration_seconds': trans.get('duration_seconds'),
                        'outro_start_seconds': trans.get('outro_start_seconds'),
                    }
            
            transitions, phase1_metrics = apply_phase1_early_transitions(
                transitions,
                outgoing_tracks,
                config,
                phase1_enabled=phase1_enabled,
                phase1_model=phase1_model
            )
            # Store Phase 1 metrics in plan for later reporting
            plan['_phase1_metrics'] = phase1_metrics
        
        # 🎵 PHASE 5: Apply micro-techniques to transitions
        if phase5_enabled:
            transitions, phase5_metrics = apply_phase5_micro_techniques(
                transitions,
                config,
                persona=persona,
                seed=None
            )
            # Store Phase 5 metrics in plan for later reporting
            plan['_phase5_metrics'] = phase5_metrics

        if has_v2_transitions:
            # Pre-extract loop segments for transitions that need them
            temp_loop_dir = _preprocess_loops(plan, config)
            # Generate v2 script with per-transition assembly
            script = _generate_liquidsoap_script_v2(plan, output_path, config, temp_loop_dir, eq_enabled=eq_enabled, eq_strategy=eq_strategy)
        else:
            # Legacy: all bass_swap or no transition_type field
            script = _generate_liquidsoap_script_legacy(plan, output_path, config, eq_enabled=eq_enabled, phase5_enabled=phase5_enabled)

        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".liq", mode="w", delete=False
        ) as tmp:
            tmp.write(script)
            script_path = tmp.name

        # Save debug copy
        debug_script_path = Path("/tmp/last_render_standalone.liq")
        debug_script_path.write_text(script)
        logger.info(f"Debug script saved to: {debug_script_path}")

        # Execute Liquidsoap and stream logs to file & logger
        logger.info(f"Starting Liquidsoap render: {output_path}")
        logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")

        # Ensure logs directory
        log_dir = os.environ.get("AUTODJ_LOG_DIR", "/tmp/autodj-logs")
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug(f"Could not create log dir: {log_dir}")

        liquidsoap_log_path = Path(log_dir) / f"liquidsoap-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.log"

        # Start Liquidsoap process and stream stdout/stderr
        # Try docker first, fall back to direct liquidsoap if available
        try:
            # Check if docker is available and container is running
            subprocess.run(["docker", "ps"], capture_output=True, timeout=5, check=True)
            
            # Get the CURRENT running Liquidsoap container ID (full ID)
            result = subprocess.run(
                ["docker", "ps", "--filter", "ancestor=radio_liquidsoap_custom:latest", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            container_ids = result.stdout.strip().split('\n')
            container_ids = [c for c in container_ids if c]
            
            if container_ids:
                running_container_id = container_ids[0]  # Get first (and usually only) running container
                
                # Copy script to a location accessible from the container
                # /srv/nas/shared is mounted as /music in the container
                container_script_path = "/music/.autodj/tmp_render_script.liq"
                host_script_dir = "/srv/nas/shared/.autodj"
                Path(host_script_dir).mkdir(parents=True, exist_ok=True)
                host_script_path = f"{host_script_dir}/tmp_render_script.liq"
                shutil.copy2(script_path, host_script_path)
                # Make readable by all (since container runs as different user)
                os.chmod(host_script_path, 0o644)
                # Use docker container for liquidsoap with CURRENT container ID
                proc = Popen(["docker", "exec", running_container_id, "liquidsoap", container_script_path], stdout=PIPE, stderr=STDOUT, text=True)
                logger.info(f"Using Liquidsoap via Docker container ({running_container_id[:12]}...)")
            else:
                raise RuntimeError("No running Liquidsoap container found")
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as docker_error:
            logger.debug(f"Docker execution failed: {docker_error}, falling back to direct liquidsoap")
            # Fall back to direct liquidsoap command
            proc = Popen(["liquidsoap", script_path], stdout=PIPE, stderr=STDOUT, text=True)
            logger.info("Using Liquidsoap directly from PATH")

        start_time = time.time()

        # Thread: stream process output to log file and logger
        def _stream_proc_output(p, logfile_path):
            try:
                with open(logfile_path, "a", encoding="utf-8") as lf:
                    while True:
                        line = p.stdout.readline()
                        if not line:
                            break
                        lf.write(line)
                        lf.flush()
                        logger.info(f"[liquidsoap] {line.rstrip()}")
            except Exception as e:
                logger.warning(f"Error streaming liquidsoap output: {e}")

        t = threading.Thread(target=_stream_proc_output, args=(proc, str(liquidsoap_log_path)), daemon=True)
        t.start()

        # Heartbeat: log elapsed time and output file size periodically
        while True:
            if proc.poll() is not None:
                break
            elapsed = time.time() - start_time
            try:
                size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
            except Exception:
                size = 0
            logger.debug(f"Render running: elapsed={elapsed:.1f}s, out_size={size} bytes")
            time.sleep(5)

        # Wait for streaming thread to finish
        t.join(timeout=2)

        if proc.returncode != 0:
            logger.error(f"Liquidsoap failed with return code {proc.returncode}")
            logger.error(f"Debug script saved to: {debug_script_path}")
            logger.error(f"Liquidsoap log: {liquidsoap_log_path}")
            _cleanup_partial_output(output_path)
            return False


        # Validate output
        if not _validate_output_file(output_path):
            logger.error("Output file validation failed")
            _cleanup_partial_output(output_path)
            return False

        # Add metadata to output
        playlist_id = plan.get("playlist_id", "autodj-playlist")
        timestamp = datetime.now().isoformat()
        _write_mix_metadata(output_path, playlist_id, timestamp, transitions=plan.get("transitions"))

        logger.info(f"✅ Render complete: {output_path}")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Render timeout after {timeout_seconds} seconds")
        _cleanup_partial_output(output_path)
        return False
    except Exception as e:
        logger.error(f"Render failed: {e}")
        _cleanup_partial_output(output_path)
        return False
    finally:
        # Cleanup temp script
        if script_path:
            try:
                Path(script_path).unlink()
                logger.debug(f"Cleaned up temp script: {script_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp script {script_path}: {e}")
        # Cleanup temp loop files
        if temp_loop_dir:
            cleanup_temp_loops(temp_loop_dir)


def render_segmented(
    transitions_json_path: str,
    output_path: str,
    config: dict,
    progress_callback: Optional[Callable] = None,
    eq_enabled: bool = True,  # NEW: Enable DJ EQ automation
) -> bool:
    """
    Render large mix in segments to reduce memory usage.

    For mixes with >max_tracks_before_segment tracks, splits into segments
    to keep peak RAM ≤200 MiB per segment instead of 512+ MiB for full mix.

    Args:
        transitions_json_path: Path to transitions.json
        output_path: Final output path
        config: Render config dict
        progress_callback: Optional callback(segment_idx, total_segments, status)
                          status: "rendering", "completed", "concatenating"
        eq_enabled: Whether to enable DJ EQ automation (default: True)

    Returns:
        True if successful, False otherwise
    """
    temp_dir = None
    segment_files = []

    try:
        # Load transitions
        with open(transitions_json_path) as f:
            plan = json.load(f)

        transitions = plan.get("transitions", [])

        # 🎛️ DJ EQ Analysis: Apply before segmentation (applies to all tracks regardless of segmentation)
        if eq_enabled:
            logger.info("🎛️ Running DJ EQ analysis on full transitions before segmentation...")
            try:
                from autodj.debug.dj_eq_logger import create_nightly_logger
                from autodj.generate.aggressive_eq_annotator import AggressiveDJEQAnnotator
                
                debug_logger = create_nightly_logger()
                logger.info("🎛️ AGGRESSIVE DJ EQ: Annotating all tracks...")
                debug_logger.log_rendering_start(output_path, len(transitions))
                
                annotator = AggressiveDJEQAnnotator(sr=44100, min_confidence=0.65)
                annotation_dir = Path("/app/data/annotations")
                annotation_dir.mkdir(parents=True, exist_ok=True)
                
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
                
                for idx, trans in enumerate(transitions):
                    file_path = trans.get("file_path", "")
                    track_id = trans.get("track_id", f"track_{idx}")
                    title = trans.get("title", f"Track {idx}")
                    
                    if not file_path or not Path(file_path).exists():
                        logger.warning(f"  ⚠️ Track {idx} not found, skipping EQ annotation")
                        debug_logger.log_error_with_context("Track file not found", track_id=track_id, context={'file_path': file_path, 'index': idx})
                        continue
                    
                    try:
                        debug_logger.log_track_analysis_start(track_id, file_path, 0)
                        track_analysis = {'sections_json': json.dumps({'sections': []}), 'energy_profile_json': json.dumps({'values': []})}
                        output_json = annotation_dir / f"eq_annotation_{track_id}.json"
                        
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(annotator.annotate_track, file_path, track_analysis, str(output_json))
                            try:
                                success = future.result(timeout=120)
                            except FuturesTimeoutError:
                                logger.warning(f"  ⏱️ {title}: Annotation timeout (>120s), skipping")
                                debug_logger.log_error_with_context("Annotation timeout", track_id=track_id, context={'file_path': file_path})
                                success = False
                        
                        if success:
                            try:
                                with open(output_json, 'r') as f:
                                    annotation = json.load(f)
                                trans['eq_annotation'] = annotation
                                eq_count = annotation.get('total_eq_skills', 0)
                                bpm = annotation.get('detected_bpm', 0)
                                logger.info(f"  ✅ {title}: {eq_count} DJ skills @ {bpm:.1f} BPM")
                                debug_logger.log_annotation_storage(track_id, eq_count, annotation)
                                skills_by_type = annotation.get('skills_by_type', {})
                                debug_logger.log_dj_skills_generated(track_id, eq_count, by_type=skills_by_type if skills_by_type else {'total': eq_count}, total_confidence_avg=annotation.get('average_confidence', 0))
                            except Exception as e:
                                logger.warning(f"  ⚠️ {title}: Failed to read annotation: {e}")
                                debug_logger.log_error_with_context(f"Failed to read annotation: {e}", track_id=track_id, context={'file_path': file_path})
                        else:
                            logger.warning(f"  ⚠️ {title}: EQ annotation returned false")
                            debug_logger.log_error_with_context("EQ annotation returned false", track_id=track_id, context={'file_path': file_path})
                    except Exception as e:
                        logger.warning(f"  ⚠️ {title}: EQ annotation error: {type(e).__name__}: {e}")
                        debug_logger.log_error_with_context(f"EQ annotation exception: {type(e).__name__}: {e}", track_id=track_id, context={'file_path': file_path, 'error_type': type(e).__name__})
                        continue
                
                logger.info("🎛️ EQ annotation complete!")
                debug_logger.save_json_analysis()
                summary = debug_logger.get_summary()
                logger.info(f"📊 Debug logs saved: {summary['debug_log']}")
                
                # Save updated transitions with EQ annotations
                with open(transitions_json_path, "w") as f:
                    json.dump(plan, f, indent=2)
                logger.debug(f"✅ Transitions JSON updated with EQ annotations")
            except ImportError:
                logger.warning("⚠️ DJ EQ modules not available, skipping EQ annotation")
            except Exception as e:
                logger.warning(f"⚠️ EQ annotation failed: {e}")
        else:
            logger.info("🎛️ DJ EQ analysis DISABLED (eq_enabled=false)")

        # Check if segmentation needed
        max_tracks_before_segment = config.get("render", {}).get(
            "max_tracks_before_segment", 10
        )

        segmenter = RenderSegmenter()
        should_segment = segmenter.should_segment(
            transitions, max_tracks_before_segment
        )

        if not should_segment:
            # Small mix, render normally
            logger.info(
                f"Mix has {len(transitions)} tracks, "
                f"rendering without segmentation"
            )
            return render(transitions_json_path, output_path, config, eq_enabled=eq_enabled)

        logger.info(
            f"Large mix detected ({len(transitions)} tracks), "
            f"using segmented rendering"
        )

        # Split into segments
        segment_size = config.get("render", {}).get("segment_size", 5)
        segments = segmenter.split_transitions(transitions, segment_size)

        if not segments:
            logger.error("Failed to create segments")
            return False

        logger.info(f"Split into {len(segments)} segments")

        # Create temp directory for segment files
        temp_dir = Path(tempfile.mkdtemp(prefix="autodj_segments_"))
        logger.debug(f"Created temp directory: {temp_dir}")

        # Render each segment
        for segment in segments:
            # Progress callback
            if progress_callback:
                progress_callback(segment.segment_index, len(segments), "rendering")

            # Generate segment-specific output
            segment_output = temp_dir / f"segment_{segment.segment_index}.mp3"

            success = _render_segment(
                segment=segment,
                plan=plan,
                output_path=str(segment_output),
                config=config,
                eq_enabled=eq_enabled,
            )

            if not success:
                logger.error(f"Segment {segment.segment_index} rendering failed")
                return False

            segment_files.append(segment_output)

            # Progress callback
            if progress_callback:
                progress_callback(segment.segment_index, len(segments), "completed")

        # Concatenate segments with crossfade blending
        if progress_callback:
            progress_callback(len(segments), len(segments), "concatenating")

        logger.info(f"Concatenating {len(segment_files)} segments...")
        success = _concatenate_segments(
            segment_files=segment_files,
            output_path=output_path,
            crossfade_duration=config.get("render", {}).get(
                "crossfade_duration_seconds", 4.0
            ),
        )

        if not success:
            logger.error("Segment concatenation failed")
            return False

        # Validate final output
        if not _validate_output_file(output_path):
            logger.error("Final output validation failed")
            return False

        # Write metadata to final output
        playlist_id = plan.get("playlist_id", "autodj-playlist")
        timestamp = datetime.now().isoformat()
        _write_mix_metadata(output_path, playlist_id, timestamp, transitions=transitions)

        logger.info(f"✅ Segmented render complete: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Segmented render failed: {e}")
        return False

    finally:
        # Cleanup temporary segments
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")


def _render_segment(
    segment: SegmentPlan,
    plan: dict,
    output_path: str,
    config: dict,
    eq_enabled: bool = True,
) -> bool:
    """
    Render a single segment to MP3.

    Args:
        segment: SegmentPlan describing this segment
        plan: Original transitions plan (for metadata)
        output_path: Output file path for this segment
        config: Render config dict
        eq_enabled: Whether to enable DJ EQ automation (default: True)

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(
            f"Rendering segment {segment.segment_index}: "
            f"tracks {segment.track_start_idx}-{segment.track_end_idx}"
        )

        # Generate segment-specific transitions JSON
        segment_plan = {
            "playlist_id": f"segment_{segment.segment_index}",
            "mix_duration_seconds": segment.estimated_duration_sec,
            "generated_at": datetime.utcnow().isoformat(),
            "transitions": segment.transitions,
        }

        # Write to temp JSON file
        segment_json = (
            Path(output_path).parent / f"segment_{segment.segment_index}.json"
        )
        with open(segment_json, "w") as f:
            json.dump(segment_plan, f, indent=2)

        # Render segment using existing render() function
        success = render(
            transitions_json_path=str(segment_json),
            output_path=output_path,
            config=config,
            timeout_seconds=None,  # No timeout for segments
            eq_enabled=eq_enabled,  # Pass through DJ EQ automation flag
        )

        # Cleanup temp JSON
        try:
            segment_json.unlink()
        except Exception:
            pass

        return success

    except Exception as e:
        logger.error(f"Segment {segment.segment_index} render failed: {e}")
        return False


def _concatenate_segments(
    segment_files: List[Path],
    output_path: str,
    crossfade_duration: float = 4.0,  # Deprecated (segments already have crossfades)
) -> bool:
    """
    Concatenate segment MP3 files directly (no blending).

    NOTE: Segment boundaries already have smooth transitions from Liquidsoap DSP.
    Simple concatenation via ffmpeg's concat demuxer is sufficient.

    Args:
        segment_files: List of segment MP3 file paths
        output_path: Output path for concatenated mix
        crossfade_duration: (DEPRECATED - not used)

    Returns:
        True if successful, False otherwise
    """
    try:
        if not segment_files:
            logger.error("No segment files to concatenate")
            return False

        if len(segment_files) == 1:
            # Single segment, just copy
            logger.debug("Single segment, copying to output")
            shutil.copy(segment_files[0], output_path)
            return True

        logger.info(
            f"Concatenating {len(segment_files)} segments (direct concat, no crossfade)"
        )

        # Create concat demuxer file (ffmpeg's efficient concatenation method)
        concat_file = Path(tempfile.mktemp(suffix=".txt"))
        try:
            with open(concat_file, "w") as f:
                for seg_file in segment_files:
                    # Escape single quotes in path
                    escaped_path = str(seg_file).replace("'", "\\'")
                    f.write(f"file '{escaped_path}'\n")

            logger.debug(f"Concat demuxer file: {concat_file}")

            # Use ffmpeg concat demuxer for fast, direct concatenation
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",  # Direct stream copy (no re-encoding)
                output_path,
            ]

            logger.debug(f"ffmpeg command: {' '.join(cmd)}")

            # Execute ffmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max for concatenation
            )

            if result.returncode != 0:
                logger.error(f"ffmpeg concatenation failed: {result.stderr}")
                return False

            logger.info("✅ Segment concatenation complete")
            return True

        finally:
            # Cleanup concat file
            try:
                concat_file.unlink()
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg concatenation timeout (10 min)")
        return False
    except Exception as e:
        logger.error(f"Segment concatenation error: {e}")
        return False


def _frames_to_seconds(frames: Optional[int], sample_rate: int = 44100) -> float:
    """Convert frame offset to seconds."""
    if frames is None or frames == 0:
        return 0.0
    return float(frames) / sample_rate


def _calculate_stretch_ratio(
    native_bpm: Optional[float], target_bpm: Optional[float]
) -> float:
    """
    Calculate time-stretch ratio for BPM matching.

    Args:
        native_bpm: Track's detected BPM
        target_bpm: Target BPM for rendering

    Returns:
        Stretch ratio (1.0 = no change, >1.0 = faster, <1.0 = slower)
    """
    if native_bpm is None or target_bpm is None or native_bpm == 0:
        return 1.0
    ratio = target_bpm / native_bpm
    # Clamp to reasonable range (±8% per SPEC.md BPM tolerance)
    ratio = max(0.92, min(1.08, ratio))
    return ratio


def _extract_m4a_segment(
    file_path: str, cue_in: float, cue_out: float, temp_dir: str, label: str = "seg"
) -> Optional[str]:
    """Pre-extract audio segment to WAV using ffmpeg for reliable Liquidsoap playback.

    In Liquidsoap 2.1.3, cue_cut() on m4a/ALAC streams calls seek() internally.
    For late cue_in positions (>~60s), the seek fails: "Seeked to 0.080 instead of 229.060".
    This causes zero-duration output and cascades to break adjacent add() sources.

    Pre-extracting to WAV bypasses the issue: ffmpeg uses -ss for accurate seeking,
    and the resulting WAV starts at position 0 (no Liquidsoap seeking required).

    Args:
        file_path: Path to source m4a/ALAC file
        cue_in: Start position in seconds
        cue_out: End position in seconds
        temp_dir: Directory for temp WAV files
        label: Label prefix for WAV filename (for debugging)

    Returns:
        Path to extracted WAV file, or None on failure
    """
    import hashlib
    key = f"{file_path}:{cue_in:.6f}:{cue_out:.6f}"
    h = hashlib.md5(key.encode()).hexdigest()[:8]
    out_path = str(Path(temp_dir) / f"{label}_{h}.wav")

    # Return cached file if already extracted
    if Path(out_path).exists() and Path(out_path).stat().st_size > 1000:
        return out_path

    cmd = [
        "ffmpeg", "-ss", str(cue_in), "-to", str(cue_out),
        "-i", file_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        out_path, "-y"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0 or not Path(out_path).exists() or Path(out_path).stat().st_size < 100:
            logger.warning(f"Segment extraction failed ({cue_in:.1f}-{cue_out:.1f}s from {Path(file_path).name}): "
                           f"{result.stderr.decode(errors='replace')[-200:]}")
            return None
        logger.debug(f"Extracted: {label} ({cue_in:.1f}-{cue_out:.1f}s) → {Path(out_path).name}")
        return out_path
    except subprocess.TimeoutExpired:
        logger.warning(f"Segment extraction timed out: {file_path}")
        return None
    except Exception as e:
        logger.warning(f"Segment extraction error: {e}")
        return None


def _container_path(p: str) -> str:
    """Map host file paths to container paths for Liquidsoap script generation.

    autodj-dev container (26e6706aaf2d, Liq 2.1.3) mounts /srv/nas/shared at
    the same path — no translation needed. The radio_liquidsoap container uses
    /music/ but we never render there (it's a live radio service).
    """
    return p


def _generate_liquidsoap_script_legacy(
    plan: dict, output_path: str, config: dict, m3u_path: str = "", eq_enabled: bool = True, phase5_enabled: bool = True
) -> str:
    """
    Generate Liquidsoap offline mixing script with pro DJ DSP.

    Architecture: sequence([tracks]) + cross(dj_transition) for sequential
    playback with bass-swap crossfades, sub-bass cleanup, and limiting.

    Args:
        plan: Transitions plan dict with transitions list
        output_path: Path to output file
        config: Render config (output format, bitrate, crossfade duration)
        m3u_path: Path to M3U playlist file (optional, for file path reference)
        eq_enabled: Whether to enable DJ EQ automation (default: True)

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 320)
    fallback_xfade = config.get("render", {}).get("crossfade_duration_seconds", 4.0)
    # Map output path to container path for script generation
    output_path = _container_path(output_path)

    transitions = plan.get("transitions", [])

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    # Compute bar-aligned crossfade duration from average BPM
    bpms = [t.get("bpm") for t in transitions if t.get("bpm")]
    if bpms:
        avg_bpm = sum(bpms) / len(bpms)
        xfade_duration = 8 * 4 * 60.0 / avg_bpm  # 8 bars
    else:
        avg_bpm = 0
        xfade_duration = fallback_xfade

    script = []

    # ==================== HEADER ====================
    script.append("# AutoDJ-Headless Pro DJ Mix")
    script.append("# Architecture: sequence() + cross() with bass swap, filter, limiter")
    eq_status = "ENABLED (per-track EQ automation)" if eq_enabled else "DISABLED"
    script.append(f"# DJ EQ Automation: {eq_status}")
    script.append(f"# Crossfade: {xfade_duration:.1f}s (8 bars at {avg_bpm:.0f} BPM)" if avg_bpm else f"# Crossfade: {xfade_duration:.1f}s (fallback)")
    script.append("")

    # ==================== TRANSITION FUNCTION ====================
    # filter.rc() WORKS inside cross() callbacks in Liquidsoap 2.1.3 (tested 2026-02-27).
    # filter.iir.butterworth does NOT work (type error). filter.rc is the correct replacement.
    # Classic DJ bass swap: cut bass on outgoing (HPF), warm start on incoming (LPF).
    hpf_cutoff = 300.0   # Hz — remove kick/bass from outgoing track during transition
    lpf_cutoff = 2500.0  # Hz — warm intro for incoming (opens up after crossfade)
    script.append("# === DJ TRANSITION (bass swap crossfade) ===")
    script.append(f"def dj_transition(a, b) =")
    script.append(f"  # Classic DJ technique: HPF outgoing (cuts bass), LPF incoming (warm entry)")
    script.append(f"  # filter.rc() works in cross() callbacks in Liq 2.1.3 (butterworth does not)")
    script.append(f"  a_cut = filter.rc(frequency={hpf_cutoff:.1f}, mode=\"high\", a.source)")
    script.append(f"  a_faded = fade.out(type=\"sin\", duration={xfade_duration:.1f}, a_cut)")
    script.append(f"  b_warm = filter.rc(frequency={lpf_cutoff:.1f}, mode=\"low\", b.source)")
    script.append(f"  b_faded = fade.in(type=\"sin\", duration={xfade_duration:.1f}, b_warm)")
    script.append(f"  add(normalize=false, [a_faded, b_faded])")
    script.append("end")
    script.append("")

    # ==================== EQ AUTOMATION HELPERS (if enabled) ====================
    # TODO: Fix Liquidsoap DSP code generation - currently has syntax errors
    # if eq_enabled:
    #     script.append("# === DJ EQ AUTOMATION HELPER FUNCTIONS ===")
    #     eq_gen = EQLiquidsoap(bpm=avg_bpm if avg_bpm > 0 else 128.0, sample_rate=44100)
    #     helpers = eq_gen.generate_liquidsoap_helpers()
    #     # Add helpers to script
    #     for line in helpers.split('\n'):
    #         if line.strip():  # Skip empty lines for brevity
    #             script.append(line)
    #     script.append("")

    # ==================== TRACK DEFINITIONS ====================
    script.append("# === TRACK DEFINITIONS ===")

    track_vars = []
    for idx, trans in enumerate(transitions):
        track_var = f"track_{idx}"
        track_vars.append(track_var)

        file_path = _container_path(trans.get("file_path", ""))
        track_id = trans.get("track_id", f"unknown_{idx}")
        native_bpm = trans.get("bpm")
        target_bpm = trans.get("target_bpm", native_bpm)
        cue_in_frames = trans.get("cue_in_frames", 0)
        cue_out_frames = trans.get("cue_out_frames")
        title = trans.get("title", "")
        artist = trans.get("artist", "")

        # Section-aware timing: use outro_start if available for cue_out
        outro_start = trans.get("outro_start_seconds")
        if outro_start is not None and outro_start > 0:
            cue_out_frames = int(outro_start * 44100)

        # Convert frames to seconds
        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)

        # Calculate stretch ratio for BPM matching
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        script.append(f"# Track {idx + 1}: {artist} - {title}" if artist else f"# Track {idx + 1}: {track_id}")
        script.append(f"#   BPM: {native_bpm} -> {target_bpm}, Stretch: {stretch_ratio:.3f}")

        # Build annotate URI with cue points (Liquidsoap 2.1 metadata-based cueing)
        annotations = []
        if cue_in_sec > 0:
            annotations.append(f"liq_cue_in={cue_in_sec:.3f}")
        if cue_out_sec > 0:
            annotations.append(f"liq_cue_out={cue_out_sec:.3f}")

        if annotations:
            annotate_str = ",".join(annotations)
            script.append(f'{track_var} = once(single("annotate:{annotate_str}:{file_path}"))')
            script.append(f"{track_var} = cue_cut({track_var})")
        else:
            script.append(f'{track_var} = once(single("{file_path}"))')

        # Decode ffmpeg.audio.raw (m4a/flac/etc) to PCM — required before stretch(), cross(), fade.*
        # single() on container-decoded formats returns ffmpeg.audio.raw, not pcm
        script.append(f"{track_var} = ffmpeg.raw.decode.audio({track_var})")

        # Apply time-stretching for BPM matching
        if stretch_ratio != 1.0:
            script.append(f"{track_var} = stretch(ratio={stretch_ratio:.3f}, {track_var})")
        
        # 🎛️ BUG FIX #3: Apply DJ EQ automation from eq_annotation fields
        eq_annotation = trans.get("eq_annotation")
        if eq_annotation and eq_enabled:
            # DISABLED: Applying EQ opportunities to body causes bass cut everywhere
            # eq_opportunities = eq_annotation.get("eq_opportunities", [])
            # Bass cut filters should ONLY apply at drop transitions, not to entire track body
            # Future: Implement segment-based EQ with proper timing from eq_annotation
            pass


        script.append("")

    # ==================== PHASE 5: MICRO-TECHNIQUES INJECTION ====================
    # NOTE: Phase 5 per-track effects are DISABLED in the legacy pipeline.
    # The legacy pipeline cannot time-window effects to specific bars — applying HPF/LPF
    # to an entire track kills the bass throughout (not just during transition zones).
    # Phase 5 belongs in the v2 pipeline where body and transition segments are separate.
    # DJ EQ techniques are provided via the dj_transition() bass swap above.
    if phase5_enabled and PHASE_5_INJECTION_AVAILABLE:
        logger.debug("Phase 5 per-track injection skipped in legacy pipeline (use v2 for segment effects)")
    
    script.append("")

    # ==================== SEQUENCING + CROSSFADE ====================
    if len(track_vars) == 1:
        # Single track — no sequence/cross needed
        script.append("# Single track, no crossfade")
        script.append(f"mixed = {track_vars[0]}")
    else:
        script.append("# === SEQUENTIAL PLAYBACK + CROSSFADE ===")
        track_list = ", ".join(track_vars)
        script.append(f"playlist = sequence([{track_list}])")
        script.append(f"mixed = cross(duration={xfade_duration:.1f}, dj_transition, playlist)")

    script.append("")

    # ==================== MASTER PROCESSING ====================
    script.append("# === MASTER PROCESSING ===")
    # NOTE: filter.rc() is DISABLED — produces silence in Liquidsoap 2.1.3 when applied to sequence()
    # filter.iir.butterworth is broken in Liquidsoap 2.2.x (GitHub issue #4124)
    # Sub-bass rumble removal is skipped for now (30Hz is below human hearing anyway)
    script.append("# Sub-bass HPF skipped: filter.rc() silences audio in Liq 2.1.3; butterworth broken in 2.2.x")
    script.append("")
    script.append("# Soft limiter (prevent clipping from overlapping transitions)")
    script.append("# Compress with proper Liquidsoap 2.1.3 parameters (times in ms, not seconds)")
    script.append("mixed = compress(threshold=-20.0, attack=50.0, release=400.0, ratio=4.0, gain=0.0, mixed)")
    script.append("")
    script.append("# Offline clock: run as fast as possible (no real-time sync)")
    script.append("mixed = clock(sync=\"none\", mixed)")
    script.append("")

    # ==================== OUTPUT ====================
    script.append("# === OUTPUT ===")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )
    elif output_format == "flac":
        script.append(
            f'output.file(%flac, "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )

    script.append("")

    return "\n".join(script)


# Backward-compatible alias for existing tests and callers
_generate_liquidsoap_script = _generate_liquidsoap_script_legacy


def _preprocess_loops(plan: dict, config: dict) -> Optional[str]:
    """
    Pre-extract loop segments for transitions that need them.

    Scans the transition list, identifies which transitions need
    loop segments (loop_hold, loop_roll), and creates WAV files
    in a temp directory.

    Args:
        plan: Transitions plan dict
        config: Render config

    Returns:
        Path to temp directory containing loop files, or None if no loops needed
    """
    transitions = plan.get("transitions", [])
    needs_loops = any(
        t.get("transition_type") in ("loop_hold", "loop_roll")
        for t in transitions
    )

    # Always create temp dir — used for loop WAVs AND m4a segment pre-extraction
    # (m4a cue_cut+seek fails in Liq 2.1.3 for late positions; WAV pre-extraction is the fix)

    temp_dir = create_temp_loop_dir()
    logger.info(f"Pre-processing loop segments in {temp_dir}")

    for idx, trans in enumerate(transitions):
        tt = trans.get("transition_type", "bass_swap")
        file_path = trans.get("file_path", "")
        bpm = trans.get("bpm") or 128.0

        if tt == "loop_hold":
            loop_start = trans.get("loop_start_seconds", 0.0)
            loop_end = trans.get("loop_end_seconds", 0.0)
            loop_repeats = trans.get("loop_repeats", 2)
            if loop_start >= 0 and loop_end > loop_start:
                output = str(Path(temp_dir) / f"t{idx}_loop.wav")
                success = create_loop_hold(
                    file_path, loop_start, loop_end, loop_repeats, output,
                )
                if success:
                    trans["_loop_wav_path"] = output
                    logger.debug(f"Transition {idx}: loop_hold WAV ready")
                else:
                    logger.warning(f"Transition {idx}: loop_hold extraction failed, falling back to bass_swap")
                    trans["transition_type"] = "bass_swap"

        elif tt == "loop_roll":
            loop_start = trans.get("loop_start_seconds", 0.0)
            roll_stages_json = trans.get("roll_stages")
            if roll_stages_json:
                try:
                    stages = json.loads(roll_stages_json) if isinstance(roll_stages_json, str) else roll_stages_json
                    # Convert lists to tuples
                    stages = [(s[0], s[1]) for s in stages]
                except (json.JSONDecodeError, IndexError, TypeError):
                    stages = [(8, 1), (4, 1), (2, 1), (1, 2)]
            else:
                stages = [(8, 1), (4, 1), (2, 1), (1, 2)]

            output = str(Path(temp_dir) / f"t{idx}_roll.wav")
            success = create_loop_roll(
                file_path, loop_start, bpm, stages, output,
            )
            if success:
                trans["_loop_wav_path"] = output
                logger.debug(f"Transition {idx}: loop_roll WAV ready")
            else:
                logger.warning(f"Transition {idx}: loop_roll extraction failed, falling back to bass_swap")
                trans["transition_type"] = "bass_swap"

    return temp_dir


def _generate_bpm_ramped_incoming(
    in_var: str,
    next_file: str,
    next_bpm: float,
    next_target: float,
    overlap_sec: float,
    in_cue_out: float,
    lpf_freq: float,
    ramp_strategy: str,
    script: list,
    in_cue_in: float = 0.0,
    temp_dir: Optional[str] = None,
) -> str:
    """
    Generate Liquidsoap code for BPM-ramped incoming track.

    Handles 4 strategies by creating time-segmented sources with different stretch ratios.

    Args:
        in_var: Variable name for incoming track (e.g., "t01_in")
        next_file: Path to incoming audio file
        next_bpm: Native BPM of incoming track
        next_target: Target BPM for incoming track
        overlap_sec: Overlap duration in seconds
        in_cue_out: Cue-out time in seconds
        lpf_freq: LPF cutoff frequency for filtering
        ramp_strategy: "no_ramp", "ramp_linear", "ramp_fast", or "ramp_delayed"
        script: List of script lines to append to
        in_cue_in: Cue-in time in seconds (default 0.0, can be overridden for drop_swap)

    Returns:
        Variable name of the final incoming track (may be different if ramping applied)
    """
    if not next_bpm or next_bpm <= 0:
        next_bpm = 128.0

    next_stretch = _calculate_stretch_ratio(next_bpm, next_target)
    bar_sec = 4 * 60.0 / next_target if next_target > 0 else 1.0

    if ramp_strategy == "no_ramp":
        # Standard: single stretch ratio for entire duration
        script.append(f'# Incoming: no BPM ramp (stay at matched target BPM)')
        _wav = _extract_m4a_segment(next_file, in_cue_in, in_cue_out, temp_dir, in_var) if temp_dir else None
        if _wav:
            script.append(f'{in_var} = once(single("{_wav}"))')
        else:
            script.append(f'{in_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
            script.append(f"{in_var} = cue_cut({in_var})")
            script.append(f"{in_var} = ffmpeg.raw.decode.audio({in_var})")
        if next_stretch != 1.0:
            script.append(f"{in_var} = stretch(ratio={next_stretch:.3f}, {in_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_var})")
        script.append(f"{in_var} = fade.in(type=\"sin\", duration={overlap_sec:.1f}, {in_var})")
        return in_var

    elif ramp_strategy == "ramp_linear":
        # Linear glide from target to native BPM over overlap
        # Split into 2 segments: first half at target, second half at native
        script.append(f'# Incoming: linear BPM ramp (target {next_target:.1f} → native {next_bpm:.1f} over {overlap_sec:.1f}s)')

        half_sec = overlap_sec / 2.0
        native_stretch = 1.0  # Native BPM = stretch ratio 1.0

        # First half: target BPM
        in_1_var = f"{in_var}_seg1"
        mid_cue = in_cue_in + half_sec
        _wav1 = _extract_m4a_segment(next_file, in_cue_in, mid_cue, temp_dir, in_1_var) if temp_dir else None
        if _wav1:
            script.append(f'{in_1_var} = once(single("{_wav1}"))')
        else:
            script.append(f'{in_1_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={mid_cue:.3f}:{next_file}"))')
            script.append(f"{in_1_var} = cue_cut({in_1_var})")
            script.append(f"{in_1_var} = ffmpeg.raw.decode.audio({in_1_var})")
        if next_stretch != 1.0:
            script.append(f"{in_1_var} = stretch(ratio={next_stretch:.3f}, {in_1_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_1_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_1_var})")
        script.append(f"{in_1_var} = fade.in(type=\"sin\", duration={half_sec:.1f}, {in_1_var})")

        # Second half: native BPM (smooth glide back)
        in_2_var = f"{in_var}_seg2"
        _wav2 = _extract_m4a_segment(next_file, mid_cue, in_cue_out, temp_dir, in_2_var) if temp_dir else None
        if _wav2:
            script.append(f'{in_2_var} = once(single("{_wav2}"))')
        else:
            script.append(f'{in_2_var} = once(single("annotate:liq_cue_in={mid_cue:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
            script.append(f"{in_2_var} = cue_cut({in_2_var})")
            script.append(f"{in_2_var} = ffmpeg.raw.decode.audio({in_2_var})")
        if native_stretch != 1.0:
            script.append(f"{in_2_var} = stretch(ratio={native_stretch:.3f}, {in_2_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_2_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_2_var})")
        script.append(f"{in_2_var} = fade.in(type=\"sin\", duration={half_sec:.1f}, {in_2_var})")

        # Layer segments
        script.append(f"{in_var} = add(normalize=false, [{in_1_var}, {in_2_var}])")
        return in_var

    elif ramp_strategy == "ramp_fast":
        # Aggressive transition in first bar, then settle to native
        script.append(f'# Incoming: fast BPM ramp (first bar aggressive, then settle to native {next_bpm:.1f})')

        fast_sec = min(bar_sec, overlap_sec / 4.0)  # First bar or 1/4 of overlap
        settle_sec = overlap_sec - fast_sec

        # First segment: target BPM (aggressive)
        in_1_var = f"{in_var}_fast"
        fast_cue_out = in_cue_in + fast_sec
        _wav1 = _extract_m4a_segment(next_file, in_cue_in, fast_cue_out, temp_dir, in_1_var) if temp_dir else None
        if _wav1:
            script.append(f'{in_1_var} = once(single("{_wav1}"))')
        else:
            script.append(f'{in_1_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={fast_cue_out:.3f}:{next_file}"))')
            script.append(f"{in_1_var} = cue_cut({in_1_var})")
            script.append(f"{in_1_var} = ffmpeg.raw.decode.audio({in_1_var})")
        if next_stretch != 1.0:
            script.append(f"{in_1_var} = stretch(ratio={next_stretch:.3f}, {in_1_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_1_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_1_var})")
        script.append(f"{in_1_var} = fade.in(type=\"sin\", duration={fast_sec:.1f}, {in_1_var})")

        # Second segment: settle at native BPM
        in_2_var = f"{in_var}_settle"
        _wav2 = _extract_m4a_segment(next_file, fast_cue_out, in_cue_out, temp_dir, in_2_var) if temp_dir else None
        if _wav2:
            script.append(f'{in_2_var} = once(single("{_wav2}"))')
        else:
            script.append(f'{in_2_var} = once(single("annotate:liq_cue_in={fast_cue_out:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
            script.append(f"{in_2_var} = cue_cut({in_2_var})")
            script.append(f"{in_2_var} = ffmpeg.raw.decode.audio({in_2_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_2_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_2_var})")
        script.append(f"{in_2_var} = fade.in(type=\"sin\", duration={settle_sec:.1f}, {in_2_var})")

        # Layer segments
        script.append(f"{in_var} = add(normalize=false, [{in_1_var}, {in_2_var}])")
        return in_var

    elif ramp_strategy == "ramp_delayed":
        # Stay at target BPM during overlap, then transition after
        script.append(f'# Incoming: delayed BPM ramp (stay matched during overlap, hint native after)')
        _wav = _extract_m4a_segment(next_file, in_cue_in, in_cue_out, temp_dir, in_var) if temp_dir else None
        if _wav:
            script.append(f'{in_var} = once(single("{_wav}"))')
        else:
            script.append(f'{in_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
            script.append(f"{in_var} = cue_cut({in_var})")
            script.append(f"{in_var} = ffmpeg.raw.decode.audio({in_var})")
        if next_stretch != 1.0:
            script.append(f"{in_var} = stretch(ratio={next_stretch:.3f}, {in_var})")
        if lpf_freq < 18000.0:
            script.append(f"{in_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_var})")
        script.append(f"{in_var} = fade.in(type=\"sin\", duration={overlap_sec:.1f}, {in_var})")
        return in_var

    else:
        # Unknown strategy, fallback to no_ramp
        return _generate_bpm_ramped_incoming(
            in_var, next_file, next_bpm, next_target, overlap_sec, in_cue_out, lpf_freq, "no_ramp", script,
            in_cue_in=in_cue_in, temp_dir=temp_dir,
        )


def _generate_liquidsoap_script_v2(
    plan: dict, output_path: str, config: dict, temp_loop_dir: Optional[str] = None, eq_enabled: bool = True, eq_strategy: str = "ladspa"
) -> str:
    """
    Generate Liquidsoap script with per-transition manual assembly (v2).

    Architecture: sequence([body, transition, body, ...]) with add() layering.
    Each transition gets its own type-specific DSP chain.
    NO cross() — full per-transition control.

    Args:
        plan: Transitions plan dict
        output_path: Path to output file
        config: Render config
        temp_loop_dir: Path to pre-extracted loop WAV files
        eq_enabled: Whether to enable DJ EQ automation (default: True)
        eq_strategy: EQ strategy to use ("ladspa", "ffmpeg", "calf", "hybrid")

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 320)
    transitions = plan.get("transitions", [])
    # Map output path to container path for script generation
    output_path = _container_path(output_path)

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    script = []
    script.append("# AutoDJ-Headless Pro DJ Mix v2")
    script.append("# Architecture: sequence([body, transition, body, ...]) with per-transition DSP")
    eq_status = "ENABLED (per-track EQ automation)" if eq_enabled else "DISABLED"
    script.append(f"# DJ EQ Automation: {eq_status}")
    script.append("")

    # Liquidsoap 2.1.3 bug: cue_cut() fails on the very first source in a sequence()
    # due to a clock initialization race condition. A 1-frame blank source as position 0
    # initializes the clock before the first cue_cut source is requested.
    script.append("# Warmup: 1-frame blank initializes Liquidsoap clock (cue_cut race condition workaround)")
    script.append("warmup = blank(duration=0.04)")
    script.append("")
    sequence_parts = ["warmup"]

    for idx, trans in enumerate(transitions):
        file_path = _container_path(trans.get("file_path", ""))
        native_bpm = trans.get("bpm")
        target_bpm = trans.get("target_bpm", native_bpm)
        cue_in_frames = trans.get("cue_in_frames", 0)
        cue_out_frames = trans.get("cue_out_frames")
        title = trans.get("title", "")
        artist = trans.get("artist", "")
        transition_type = trans.get("transition_type", "bass_swap")
        overlap_bars = trans.get("overlap_bars", 8)
        hpf_freq = trans.get("hpf_frequency", 200.0)
        lpf_freq = trans.get("lpf_frequency", 2500.0)
        incoming_start_sec = trans.get("incoming_start_seconds")
        next_track_id = trans.get("next_track_id")

        # Section-aware timing: use outro_start if available for cue_out
        outro_start = trans.get("outro_start_seconds")
        if outro_start is not None and outro_start > 0:
            cue_out_frames = int(outro_start * 44100)

        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        effective_bpm = native_bpm if native_bpm and native_bpm > 0 else 128.0
        bar_duration = 4 * 60.0 / effective_bpm
        overlap_sec = overlap_bars * bar_duration

        # 🎵 PHASE 1: Extract early transition timing if available
        # Phase 1 enables starting the incoming track 16+ bars BEFORE the outro
        phase1_metadata = trans.get("phase1_metadata", {})
        phase1_enabled_flag = phase1_metadata.get("enabled", False)
        phase1_crossfade_start = phase1_metadata.get("crossfade_start_seconds")
        
        # If Phase 1 is enabled, calculate the actual transition start time from outgoing track start
        # This represents when to begin playing the incoming track (relative to timeline)
        actual_transition_start_sec = phase1_crossfade_start if phase1_enabled_flag and phase1_crossfade_start is not None else None
        
        # For Phase 1, we also need to adjust how the body ends (it should end at the crossfade start, not overlap_sec before cue_out)
        if actual_transition_start_sec is not None and phase1_enabled_flag:
            # Phase 1 changes the overlap timing: incoming starts at phase1_crossfade_start
            # This creates a longer, earlier transition
            logger.debug(f"Phase 1: Transition {idx} early start at {actual_transition_start_sec:.1f}s")

        is_last_track = (next_track_id is None)
        next_trans = transitions[idx + 1] if idx + 1 < len(transitions) else None

        # === TRACK BODY ===
        # Body: from cue_in (or after prev transition's incoming head) to transition start
        body_var = f"body_{idx}"

        # Determine body start: if this track is incoming from a previous transition,
        # start from where the transition head ended
        if idx > 0:
            prev_trans = transitions[idx - 1]
            prev_incoming_start = prev_trans.get("incoming_start_seconds")
            if prev_incoming_start is not None:
                body_cue_in = prev_incoming_start
            else:
                # Fallback: start from overlap_bars into the track
                prev_overlap = prev_trans.get("overlap_bars", 8)
                prev_bpm = prev_trans.get("bpm") or 128.0
                body_cue_in = prev_overlap * 4 * 60.0 / prev_bpm
        else:
            body_cue_in = cue_in_sec

        # Determine body end: where the transition zone starts
        if is_last_track:
            body_cue_out = cue_out_sec
        else:
            # 🎵 PHASE 1: If early transition enabled, body ends at phase1_crossfade_start
            if actual_transition_start_sec is not None and phase1_enabled_flag:
                # Phase 1: incoming track starts at crossfade_start, so body ends then
                body_cue_out = actual_transition_start_sec
            else:
                # Standard: body ends overlap_sec before cue_out
                if cue_out_sec > overlap_sec:
                    body_cue_out = cue_out_sec - overlap_sec
                else:
                    body_cue_out = cue_out_sec

        # === PRE-CHECK: Extend bass cut from previous LPF transition through body to drop ===
        # When a bass_swap/loop_hold/loop_roll incoming had LPF applied and the track's drop
        # falls within the body range, hold the bass cut until the drop and slam full bass there.
        _body_drop_sec = None
        _body_lpf_freq = 2500.0
        _body_prev_tt = "bass_swap"
        _body_split_vars = None  # Set to [predrop_var, postdrop_var] when body is split
        if idx > 0:
            _ptrans = transitions[idx - 1]
            _ptt = _ptrans.get("transition_type", "bass_swap")
            _pdrop = _ptrans.get("drop_position_seconds")
            _plpf = _ptrans.get("lpf_frequency", 2500.0)
            if (_ptt in {"bass_swap", "loop_hold", "loop_roll", "eq_blend"} and
                    _pdrop is not None and _plpf < 18000.0 and
                    _pdrop > body_cue_in + 2.0 and _pdrop < body_cue_out - 2.0):
                _body_drop_sec = _pdrop
                _body_lpf_freq = _plpf
                _body_prev_tt = _ptt

        script.append(f"# === TRACK {idx} BODY: {artist} - {title} ===" if artist else f"# === TRACK {idx} BODY ===")
        script.append(f"#   BPM: {native_bpm} -> {target_bpm}, Stretch: {stretch_ratio:.3f}")

        def _emit_body_segment(seg_var, seg_start, seg_end):
            """Emit Liquidsoap source lines for one body sub-segment."""
            _seg_wav = _extract_m4a_segment(file_path, seg_start, seg_end, temp_loop_dir, seg_var) if temp_loop_dir else None
            if _seg_wav:
                script.append(f'{seg_var} = once(single("{_seg_wav}"))')
            else:
                _seg_ann = f"liq_cue_in={seg_start:.3f},liq_cue_out={seg_end:.3f}"
                script.append(f'{seg_var} = once(single("annotate:{_seg_ann}:{file_path}"))')
                script.append(f"{seg_var} = cue_cut({seg_var})")
                script.append(f"{seg_var} = ffmpeg.raw.decode.audio({seg_var})")
            if stretch_ratio != 1.0:
                script.append(f"{seg_var} = stretch(ratio={stretch_ratio:.3f}, {seg_var})")

        if _body_drop_sec is not None:
            # 🥁 DROP-SPLIT BODY: Bass cut held until detected drop, then full bass slams
            script.append(f"# 🥁 DROP-SPLIT: Bass LPF@{_body_lpf_freq:.0f}Hz [{body_cue_in:.1f}→{_body_drop_sec:.1f}s], Full bass [{_body_drop_sec:.1f}→{body_cue_out:.1f}s]")
            _pre_bvar = f"{body_var}_predrop"
            _post_bvar = f"{body_var}_postdrop"

            # Pre-drop: carry bass cut from the transition (LPF still applied)
            _emit_body_segment(_pre_bvar, body_cue_in, _body_drop_sec)
            script.append(f"# Bass cut ({_body_prev_tt}): LPF@{_body_lpf_freq:.0f}Hz held to drop")
            script.append(f"{_pre_bvar} = filter.rc(frequency={_body_lpf_freq:.1f}, mode=\"low\", {_pre_bvar})")

            # Post-drop: full bass slam — no filter!
            _emit_body_segment(_post_bvar, _body_drop_sec, body_cue_out)

            # Inject predrop+postdrop directly into outer sequence (avoid nested sequence in Liq 2.1.3)
            _body_split_vars = [_pre_bvar, _post_bvar]
        else:
            # Normal body: single contiguous segment
            annotations = []
            if body_cue_in > 0:
                annotations.append(f"liq_cue_in={body_cue_in:.3f}")
            if body_cue_out > 0:
                annotations.append(f"liq_cue_out={body_cue_out:.3f}")

            # Pre-extract m4a segment to WAV: Liq 2.1.3 cue_cut seek fails for late positions
            if annotations and temp_loop_dir:
                wav_path = _extract_m4a_segment(
                    file_path, body_cue_in, body_cue_out, temp_loop_dir, f"body_{idx}"
                )
                if wav_path:
                    script.append(f'{body_var} = once(single("{wav_path}"))')
                    # WAV is already PCM: no cue_cut or ffmpeg.raw.decode.audio needed
                else:
                    # Fallback: annotate+cue_cut (may fail for late cue_in positions)
                    annotate_str = ",".join(annotations)
                    script.append(f'{body_var} = once(single("annotate:{annotate_str}:{file_path}"))')
                    script.append(f"{body_var} = cue_cut({body_var})")
                    script.append(f"{body_var} = ffmpeg.raw.decode.audio({body_var})")
            elif annotations:
                annotate_str = ",".join(annotations)
                script.append(f'{body_var} = once(single("annotate:{annotate_str}:{file_path}"))')
                script.append(f"{body_var} = cue_cut({body_var})")
                script.append(f"{body_var} = ffmpeg.raw.decode.audio({body_var})")
            else:
                script.append(f'{body_var} = once(single("{file_path}"))')
                script.append(f"{body_var} = ffmpeg.raw.decode.audio({body_var})")

            if stretch_ratio != 1.0:
                script.append(f"{body_var} = stretch(ratio={stretch_ratio:.3f}, {body_var})")

        # === VOCAL PREVIEW MIXING (Phase 2026-02-12) ===
        # Layer vocal preview from next track during non-vocal sections
        if trans.get("vocal_preview_wav") and trans.get("vocal_preview_enabled"):
            vocal_preview_wav = trans.get("vocal_preview_wav")
            vocal_loop_label = trans.get("vocal_preview_loop", "unknown")
            vocal_prominence = trans.get("vocal_preview_prominence", 0.0)
            
            script.append(f"# Vocal preview mixing: next track's {vocal_loop_label} ({vocal_prominence:.1%} vocal)")
            script.append(f'vocal_preview_{idx} = once(single("{vocal_preview_wav}"))')
            
            # Layer vocal preview using add() (mixing, not crossfade)
            script.append(f'{body_var} = add(normalize=false, [{body_var}, vocal_preview_{idx}])')
            script.append(f"# Note: Vocal preview was pre-processed and pre-mixed by preprocess_vocal_previews.py")

        # 🎛️ BUG FIX #3: Apply DJ EQ automation from eq_annotation fields (v2 script)
        eq_annotation = trans.get("eq_annotation")
        if eq_annotation and eq_enabled:
            # DISABLED: Applying EQ opportunities to body causes bass cut everywhere
            # eq_opportunities = eq_annotation.get("eq_opportunities", [])
            # Bass cut filters should ONLY apply at drop transitions, not to entire track body
            # Future: Implement segment-based EQ with proper timing from eq_annotation
            pass



        script.append("")
        if _body_split_vars is not None:
            # Drop-split: inject predrop and postdrop directly (avoid nested sequence in Liq 2.1.3)
            sequence_parts.extend(_body_split_vars)
        else:
            sequence_parts.append(body_var)

        # === TRANSITION ZONE ===
        if not is_last_track and next_trans:
            next_file = _container_path(next_trans.get("file_path", ""))
            next_bpm = next_trans.get("bpm")
            next_target = next_trans.get("target_bpm", next_bpm)
            next_stretch = _calculate_stretch_ratio(next_bpm, next_target)
            next_drop_sec = trans.get("drop_position_seconds")

            trans_var = f"transition_{idx}_{idx+1}"
            out_var = f"t{idx}{idx+1}_out"
            in_var = f"t{idx}{idx+1}_in"

            # 🎵 PHASE 1: Adjust transition timing for early start
            # For Phase 1 early transitions, the outgoing track needs to extend into the drop section
            # and the incoming track needs to start earlier (at phase1_crossfade_start)
            phase1_overlap_sec = overlap_sec
            phase1_out_start = body_cue_out
            phase1_out_end = cue_out_sec
            phase1_in_cue_in = 0.0
            phase1_in_cue_out = overlap_sec
            phase1_fade_duration = overlap_sec
            
            if actual_transition_start_sec is not None and phase1_enabled_flag:
                # Phase 1: Calculate adjusted timing based on crossfade_start
                phase1_early_bars = phase1_metadata.get("early_transition_bars", 16)
                phase1_duration_bars = phase1_metadata.get("crossfade_duration_bars", overlap_bars)
                
                # The outgoing track should play from body_cue_out to the actual crossfade end
                phase1_out_start = body_cue_out
                phase1_out_end = cue_out_sec  # Still ends at the original outro_end
                
                # The incoming track starts at phase1_crossfade_start
                # Duration is from crossfade_start to cue_out_sec
                phase1_crossfade_duration = cue_out_sec - actual_transition_start_sec if cue_out_sec > actual_transition_start_sec else overlap_sec
                phase1_in_cue_out = phase1_crossfade_duration
                phase1_overlap_sec = phase1_crossfade_duration
                phase1_fade_duration = phase1_crossfade_duration
                
                script.append(f"# 🎵 Phase 1: Early transition ({phase1_early_bars} bars before outro)")
                script.append(f"#   Outgoing plays from {phase1_out_start:.1f}s to {phase1_out_end:.1f}s")
                script.append(f"#   Incoming starts at {actual_transition_start_sec:.1f}s for {phase1_crossfade_duration:.1f}s")

            script.append(f"# === TRANSITION {idx}->{idx+1}: {transition_type.upper()} ({overlap_bars} bars) ===")

            if transition_type == "loop_hold" and trans.get("_loop_wav_path"):
                # Outgoing: pre-extracted loop WAV
                loop_wav = trans["_loop_wav_path"]
                script.append(f'# Outgoing: pre-extracted loop')
                script.append(f'{out_var} = once(single("{loop_wav}"))')
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = filter.rc(frequency={hpf_freq:.1f}, mode=\"high\", {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={phase1_fade_duration:.1f}, {out_var})")

                # Incoming: with BPM ramping strategy
                # 🎵 PHASE 1: Use Phase 1-adjusted cue times if available
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, phase1_overlap_sec, phase1_in_cue_out,
                    lpf_freq, bpm_ramp_strat, script, temp_dir=temp_loop_dir
                )

            elif transition_type == "loop_roll" and trans.get("_loop_wav_path"):
                # Outgoing: pre-extracted roll WAV
                roll_wav = trans["_loop_wav_path"]
                script.append(f'# Outgoing: progressive halving roll')
                script.append(f'{out_var} = once(single("{roll_wav}"))')
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = filter.rc(frequency={hpf_freq:.1f}, mode=\"high\", {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={phase1_fade_duration:.1f}, {out_var})")

                # Incoming: with BPM ramping (last half of overlap for loop_roll)
                # 🎵 PHASE 1: Adjust for Phase 1 timing
                in_overlap_sec = phase1_overlap_sec / 2.0  # Fade in over last half of Phase 1 overlap
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, in_overlap_sec, phase1_in_cue_out,
                    lpf_freq, bpm_ramp_strat, script, temp_dir=temp_loop_dir
                )

            elif transition_type == "drop_swap":
                # Short punchy transition: fast fade, no LPF on incoming
                out_start = phase1_out_start  # Use Phase 1-adjusted start
                out_end = phase1_out_end      # Use Phase 1-adjusted end

                script.append(f'# Outgoing: fast fade out')
                _seg_wav = _extract_m4a_segment(
                    file_path, out_start, out_end, temp_loop_dir, f"t{idx}{idx+1}_out"
                ) if temp_loop_dir else None
                if _seg_wav:
                    script.append(f'{out_var} = once(single("{_seg_wav}"))')
                else:
                    script.append(f'{out_var} = once(single("annotate:liq_cue_in={out_start:.3f},liq_cue_out={out_end:.3f}:{file_path}"))')
                    script.append(f"{out_var} = cue_cut({out_var})")
                    script.append(f"{out_var} = ffmpeg.raw.decode.audio({out_var})")
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={phase1_fade_duration:.1f}, {out_var})")

                # Incoming at drop position: with BPM ramping, but NO LPF (full power)
                drop_sec = next_drop_sec if next_drop_sec else 0.0
                drop_end = drop_sec + phase1_overlap_sec  # Use Phase 1-adjusted overlap
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")

                # For drop_swap with BPM ramping, use no filter (lpf_freq = 20000 means off)
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, phase1_overlap_sec, drop_end,
                    20000.0, bpm_ramp_strat, script, in_cue_in=drop_sec, temp_dir=temp_loop_dir
                )

            elif transition_type == "eq_blend":
                # Long gradual blend with frequency sweep over first 1 bar
                # Calculate 1 bar duration (4 beats at target BPM)
                bar_sec = (60.0 / target_bpm) * 4
                bar_sec = min(bar_sec, phase1_overlap_sec / 4.0)  # Don't exceed 1/4 of Phase 1 overlap

                out_start = phase1_out_start  # Use Phase 1-adjusted start
                out_end = phase1_out_end      # Use Phase 1-adjusted end

                script.append(f'# Outgoing: EQ sweep over first bar, then fade out')

                # Aggressive HPF for first 1 bar (strong bass cut)
                out_bar1_var = f"{out_var}_bar1"
                _bar1_wav = _extract_m4a_segment(file_path, out_start, out_start + bar_sec, temp_loop_dir, out_bar1_var) if temp_loop_dir else None
                if _bar1_wav:
                    script.append(f'{out_bar1_var} = once(single("{_bar1_wav}"))')
                else:
                    script.append(f'{out_bar1_var} = once(single("annotate:liq_cue_in={out_start:.3f},liq_cue_out={out_start + bar_sec:.3f}:{file_path}"))')
                    script.append(f"{out_bar1_var} = cue_cut({out_bar1_var})")
                    script.append(f"{out_bar1_var} = ffmpeg.raw.decode.audio({out_bar1_var})")
                if stretch_ratio != 1.0:
                    script.append(f"{out_bar1_var} = stretch(ratio={stretch_ratio:.3f}, {out_bar1_var})")
                # DISABLED: HPF removed - let Phase 5 techniques handle bass cuts (bars 8-10.7)
                # script.append(f"{out_bar1_var} = filter.rc(frequency=200.0, mode=\"high\", {out_bar1_var})")
                script.append(f"{out_bar1_var} = fade.out(type=\"sin\", duration={phase1_fade_duration:.1f}, {out_bar1_var})")

                # Subtle HPF for remaining bars (settle into steady state)
                if phase1_overlap_sec > bar_sec * 1.5:
                    out_remaining_var = f"{out_var}_remain"
                    _remain_wav = _extract_m4a_segment(file_path, out_start + bar_sec, out_end, temp_loop_dir, out_remaining_var) if temp_loop_dir else None
                    if _remain_wav:
                        script.append(f'{out_remaining_var} = once(single("{_remain_wav}"))')
                    else:
                        script.append(f'{out_remaining_var} = once(single("annotate:liq_cue_in={out_start + bar_sec:.3f},liq_cue_out={out_end:.3f}:{file_path}"))')
                        script.append(f"{out_remaining_var} = cue_cut({out_remaining_var})")
                        script.append(f"{out_remaining_var} = ffmpeg.raw.decode.audio({out_remaining_var})")
                    if stretch_ratio != 1.0:
                        script.append(f"{out_remaining_var} = stretch(ratio={stretch_ratio:.3f}, {out_remaining_var})")
                    # DISABLED: HPF removed - let Phase 5 techniques handle bass cuts
                    # script.append(f"{out_remaining_var} = filter.rc(frequency={hpf_freq:.1f}, mode=\"high\", {out_remaining_var})")
                    script.append(f"{out_remaining_var} = fade.out(type=\"sin\", duration={phase1_fade_duration - bar_sec:.1f}, {out_remaining_var})")
                    script.append(f"{out_var} = add(normalize=false, [{out_bar1_var}, {out_remaining_var}])")
                else:
                    script.append(f"{out_var} = {out_bar1_var}")

                # Incoming: warm LPF for first bar, then open up gradually
                in_cue_out = phase1_in_cue_out  # Use Phase 1-adjusted timing
                script.append(f'# Incoming: EQ sweep over first bar, then open up')

                # Aggressive LPF for first 1 bar (keep it warm, not bright)
                in_bar1_var = f"{in_var}_bar1"
                _in_bar1_wav = _extract_m4a_segment(next_file, 0.0, bar_sec, temp_loop_dir, in_bar1_var) if temp_loop_dir else None
                if _in_bar1_wav:
                    script.append(f'{in_bar1_var} = once(single("{_in_bar1_wav}"))')
                else:
                    script.append(f'{in_bar1_var} = once(single("annotate:liq_cue_in=0.0,liq_cue_out={bar_sec:.3f}:{next_file}"))')
                    script.append(f"{in_bar1_var} = cue_cut({in_bar1_var})")
                    script.append(f"{in_bar1_var} = ffmpeg.raw.decode.audio({in_bar1_var})")
                if next_stretch != 1.0:
                    script.append(f"{in_bar1_var} = stretch(ratio={next_stretch:.3f}, {in_bar1_var})")
                script.append(f"{in_bar1_var} = filter.rc(frequency=500.0, mode=\"low\", {in_bar1_var})")
                script.append(f"{in_bar1_var} = fade.in(type=\"sin\", duration={bar_sec:.1f}, {in_bar1_var})")

                # Open filter for remaining bars (gradually brighten)
                if in_cue_out > bar_sec * 1.5:
                    in_remaining_var = f"{in_var}_remain"
                    _in_remain_wav = _extract_m4a_segment(next_file, bar_sec, in_cue_out, temp_loop_dir, in_remaining_var) if temp_loop_dir else None
                    if _in_remain_wav:
                        script.append(f'{in_remaining_var} = once(single("{_in_remain_wav}"))')
                    else:
                        script.append(f'{in_remaining_var} = once(single("annotate:liq_cue_in={bar_sec:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
                        script.append(f"{in_remaining_var} = cue_cut({in_remaining_var})")
                        script.append(f"{in_remaining_var} = ffmpeg.raw.decode.audio({in_remaining_var})")
                    if next_stretch != 1.0:
                        script.append(f"{in_remaining_var} = stretch(ratio={next_stretch:.3f}, {in_remaining_var})")
                    if lpf_freq < 18000.0:
                        script.append(f"{in_remaining_var} = filter.rc(frequency={lpf_freq:.1f}, mode=\"low\", {in_remaining_var})")
                    script.append(f"{in_remaining_var} = fade.in(type=\"sin\", duration={in_cue_out - bar_sec:.1f}, {in_remaining_var})")
                    script.append(f"{in_var} = add(normalize=false, [{in_bar1_var}, {in_remaining_var}])")
                else:
                    script.append(f"{in_var} = {in_bar1_var}")

            else:
                # bass_swap (default) - WITH SEGMENT-BASED EQ STRATEGY
                out_start = phase1_out_start  # Use Phase 1-adjusted start
                out_end = phase1_out_end      # Use Phase 1-adjusted end

                script.append(f'# Outgoing: Segment-based EQ (strategy: {eq_strategy}) + fade out')

                # Pre-extract outgoing segment to WAV to avoid Liq 2.1.3 cue_cut seek failure
                _out_seg_wav = _extract_m4a_segment(
                    file_path, out_start, out_end, temp_loop_dir, f"t{idx}{idx+1}_out"
                ) if temp_loop_dir else None
                _out_seg_file = _out_seg_wav if _out_seg_wav else file_path
                _out_seg_cue_in = 0.0 if _out_seg_wav else out_start
                _out_seg_cue_out = 0.0 if _out_seg_wav else out_end

                # Apply segment EQ strategy to outgoing drop segment
                eq_lines = apply_segment_eq(
                    segment_var=out_var,
                    file_path=_out_seg_file,
                    cue_in=_out_seg_cue_in,
                    cue_out=_out_seg_cue_out,
                    bpm=native_bpm or 128.0,
                    overlap_bars=overlap_bars,
                    strategy=eq_strategy
                )
                script.extend(eq_lines)
                
                # Apply stretch and fade
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={phase1_fade_duration:.1f}, {out_var})")

                # Incoming: with BPM ramping strategy
                # 🎵 PHASE 1: Use Phase 1-adjusted cue times if available
                in_cue_out_final = phase1_in_cue_out
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")

                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, phase1_overlap_sec, in_cue_out_final,
                    lpf_freq, bpm_ramp_strat, script, temp_dir=temp_loop_dir
                )

            # Layer outgoing + incoming
            script.append(f"{trans_var} = add(normalize=false, [{out_var}, {in_var}])")
            
            # 🎵 PHASE 5: APPLY MICRO-TECHNIQUES TO TRANSITION
            phase5_techniques = trans.get("phase5_micro_techniques")
            if phase5_techniques:
                try:
                    from autodj.render.phase5_liquidsoap_codegen import generate_phase5_liquidsoap
                    phase5_code = generate_phase5_liquidsoap(
                        phase5_techniques,
                        transition_var=trans_var,
                        bpm=effective_bpm,
                        overlap_bars=overlap_bars,
                        transition_type=transition_type
                    )
                    if phase5_code:
                        script.append("")
                        script.append(phase5_code)
                except ImportError:
                    logger.debug("Phase 5 codegen not available")
                except Exception as e:
                    logger.warning(f"Phase 5 codegen error: {e}")
            
            script.append("")
            sequence_parts.append(trans_var)

    # === ASSEMBLY ===
    script.append("# === ASSEMBLY ===")
    if len(sequence_parts) == 1:
        script.append(f"mixed = {sequence_parts[0]}")
    else:
        parts_str = ", ".join(sequence_parts)
        script.append(f"mixed = sequence([{parts_str}])")
    script.append("")

    # === MASTER PROCESSING ===
    script.append("# === MASTER PROCESSING ===")
    script.append("# Sub-bass HPF skipped: filter.rc() silences audio in Liq 2.1.3; butterworth broken in 2.2.x")
    script.append("")
    script.append("# Soft limiter (prevent clipping from overlapping transitions)")
    script.append("# Compress with proper Liquidsoap 2.1.3 parameters (times in ms, not seconds)")
    script.append("mixed = compress(threshold=-20.0, attack=50.0, release=400.0, ratio=4.0, gain=0.0, mixed)")
    script.append("")
    script.append("# Offline clock: run as fast as possible (no real-time sync)")
    script.append("mixed = clock(sync=\"none\", mixed)")
    script.append("")

    # === OUTPUT ===
    script.append("# === OUTPUT ===")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )
    elif output_format == "flac":
        script.append(
            f'output.file(%flac, "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )
    else:
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, mixed)'
        )
    script.append("")

    return "\n".join(script)


def _validate_output_file(output_path: str) -> bool:
    """
    Validate rendered output file (SPEC.md § 10.3).

    Args:
        output_path: Path to output file

    Returns:
        True if valid, False otherwise
    """
    try:
        output_file = Path(output_path)

        # Check file exists
        if not output_file.exists():
            logger.error(f"Output file does not exist: {output_path}")
            return False

        # Check minimum size (1 MiB per SPEC.md § 10.3)
        min_size_bytes = 1024 * 1024
        file_size = output_file.stat().st_size
        if file_size < min_size_bytes:
            logger.error(f"Output file too small: {file_size} bytes (minimum {min_size_bytes})")
            return False

        logger.debug(f"Output validation passed: {output_path} ({file_size} bytes)")
        return True

    except Exception as e:
        logger.error(f"Output validation failed: {e}")
        return False


def _write_mix_metadata(output_path: str, playlist_id: str, timestamp: str, transitions: Optional[list] = None) -> bool:
    """
    Write ID3 metadata to output mix file (SPEC.md § 4.4).

    Args:
        output_path: Path to output file
        playlist_id: Playlist identifier
        timestamp: Generation timestamp (ISO format)
        transitions: Optional list of transition dicts for richer metadata

    Returns:
        True if successful, False otherwise
    """
    try:
        output_file = Path(output_path)
        if not output_file.exists():
            logger.warning(f"Output file not found for metadata writing: {output_path}")
            return False

        year = timestamp[:4]  # Extract year from ISO timestamp
        album_name = f"AutoDJ Mix {timestamp[:10]}"  # YYYY-MM-DD
        genre = "DJ Mix"

        # Build richer title/artist from transitions metadata
        title = f"AutoDJ Mix {timestamp[:10]}"
        artist = "AutoDJ"
        if transitions:
            # Use seed track (first) artist for title
            seed_artist = transitions[0].get("artist")
            if seed_artist:
                title = f"AutoDJ Mix - {seed_artist} et al."
                artist = "AutoDJ"

        # Handle MP3 files
        if output_path.lower().endswith('.mp3'):
            try:
                # Try to read/create ID3 tags
                try:
                    audio = EasyID3(output_path)
                except Exception as e:
                    # If ID3 header missing, initialize it using mutagen's ID3 class
                    if "doesn't start with an ID3 tag" in str(e):
                        logger.debug(f"Initializing ID3v2 header for {output_path}")
                        from mutagen.id3 import ID3
                        try:
                            # Create empty ID3v2.4 tag
                            audio = ID3()
                            audio.save(output_path, v2_version=4)
                            # Now read it back as EasyID3
                            audio = EasyID3(output_path)
                        except Exception as init_err:
                            logger.warning(f"Failed to initialize ID3 header: {init_err}")
                            return False
                    else:
                        raise

                # Write metadata
                audio['title'] = title
                audio['artist'] = artist
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added ID3 metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write ID3 tags to MP3: {e}")
                return False

        # Handle FLAC files
        elif output_path.lower().endswith('.flac'):
            try:
                audio = FLAC(output_path)
                audio['title'] = title
                audio['artist'] = artist
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added VORBIS metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write VORBIS tags to FLAC: {e}")
                return False

        else:
            logger.debug(f"Unsupported format for metadata: {output_path}")
            return False

        return True

    except Exception as e:
        logger.error(f"Metadata writing failed: {e}")
        return False


def _cleanup_partial_output(output_path: str) -> None:
    """
    Clean up partial or failed output files.

    Args:
        output_path: Path to output file to remove
    """
    try:
        output_file = Path(output_path)
        if output_file.exists():
            output_file.unlink()
            logger.debug(f"Cleaned up partial output: {output_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up output file {output_path}: {e}")


class RenderEngine:
    """Liquidsoap offline rendering orchestrator."""

    def __init__(self, config: dict):
        """
        Initialize render engine.

        Args:
            config: Configuration dict
        """
        self.config = config
        logger.info("RenderEngine initialized")

    def render_playlist(
        self,
        transitions_json_path: str,
        playlist_m3u_path: str,
        output_path: str,
        timeout_seconds: Optional[int] = None,
        eq_enabled: bool = True,
    ) -> bool:
        """
        Render playlist to final mix.

        Args:
            transitions_json_path: Path to transitions.json
            playlist_m3u_path: Path to playlist.m3u (for track reference)
            output_path: Output mix file path
            timeout_seconds: Max render time in seconds (None = no timeout)
            eq_enabled: Enable DJ EQ automation (default: True)

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Starting render: {output_path}")
        logger.info(f"[DEBUG] render_playlist eq_enabled={eq_enabled}")
        script_path = None

        # Load transitions plan
        try:
            with open(transitions_json_path, "r") as f:
                plan = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load transitions: {e}")
            return False

        # Load playlist for file paths
        try:
            with open(playlist_m3u_path, "r") as f:
                playlist_lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to load playlist: {e}")
            return False

        # Map transitions to file paths from M3U
        file_paths = [
            line.strip() for line in playlist_lines
            if not line.startswith("#") and line.strip()
        ]

        for idx, trans in enumerate(plan.get("transitions", [])):
            if idx < len(file_paths):
                trans["file_path"] = file_paths[idx]

        # 🎛️ NEW: Aggressive DJ EQ Annotation (Beat-Synced EQ System)
        # Annotate each track with EQ opportunities before rendering
        debug_logger = None
        if eq_enabled:  # ← ONLY RUN IF EQ IS ENABLED!
            try:
                from autodj.debug.dj_eq_logger import create_nightly_logger
                from autodj.generate.aggressive_eq_annotator import AggressiveDJEQAnnotator
                
                debug_logger = create_nightly_logger()
                logger.info("🎛️ AGGRESSIVE DJ EQ: Annotating tracks with beat-synced opportunities...")
                debug_logger.log_rendering_start(output_path, len(plan.get("transitions", [])))
                
                annotator = AggressiveDJEQAnnotator(sr=44100, min_confidence=0.65)
                
                # Use persistent directory for DJ EQ annotations
                annotation_dir = Path("/app/data/annotations")
                annotation_dir.mkdir(parents=True, exist_ok=True)
                
                # Import threading for timeout handling
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
                
                for idx, trans in enumerate(plan.get("transitions", [])):
                    file_path = trans.get("file_path", "")
                    track_id = trans.get("track_id", f"track_{idx}")
                    title = trans.get("title", f"Track {idx}")
                    
                    if not file_path or not Path(file_path).exists():
                        logger.warning(f"  ⚠️ Track {idx} not found, skipping EQ annotation")
                        debug_logger.log_error_with_context(
                            "Track file not found",
                            track_id=track_id,
                            context={'file_path': file_path, 'index': idx}
                        )
                        continue
                    
                    try:
                        debug_logger.log_track_analysis_start(track_id, file_path, 0)
                        
                        track_analysis = {
                            'sections_json': json.dumps({'sections': []}),
                            'energy_profile_json': json.dumps({'values': []}),
                        }
                        
                        # Write to /tmp (writable location, not NAS)
                        output_json = annotation_dir / f"eq_annotation_{track_id}.json"
                        
                        # Run annotation with 120-second timeout (librosa can be slow on NAS)
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(annotator.annotate_track, file_path, track_analysis, str(output_json))
                            try:
                                success = future.result(timeout=120)  # 2 minutes per track
                            except FuturesTimeoutError:
                                logger.warning(f"  ⏱️ {title}: Annotation timeout (>120s), skipping DJ EQ for this track")
                                debug_logger.log_error_with_context(
                                    "Annotation timeout after 120s",
                                    track_id=track_id,
                                    context={'file_path': file_path}
                                )
                                success = False
                        
                        if success:
                            try:
                                with open(output_json, 'r') as f:
                                    annotation = json.load(f)
                                
                                trans['eq_annotation'] = annotation
                                eq_count = annotation.get('total_eq_skills', 0)
                                bpm = annotation.get('detected_bpm', 0)
                                
                                logger.info(f"  ✅ {title}: {eq_count} DJ skills @ {bpm:.1f} BPM")
                                debug_logger.log_annotation_storage(track_id, eq_count, annotation)
                                
                                skills_by_type = annotation.get('skills_by_type', {})
                                debug_logger.log_dj_skills_generated(
                                    track_id, eq_count,
                                    by_type=skills_by_type if skills_by_type else {'total': eq_count},
                                    total_confidence_avg=annotation.get('average_confidence', 0)
                                )
                            except Exception as e:
                                logger.warning(f"  ⚠️ {title}: Failed to read annotation file: {e}")
                                debug_logger.log_error_with_context(
                                    f"Failed to read annotation: {e}",
                                    track_id=track_id,
                                    context={'file_path': file_path}
                                )
                        else:
                            logger.warning(f"  ⚠️ {title}: EQ annotation returned false")
                            debug_logger.log_error_with_context(
                                "EQ annotation returned false",
                                track_id=track_id,
                                context={'file_path': file_path}
                            )
                    
                    except Exception as e:
                        logger.warning(f"  ⚠️ {title}: EQ annotation error: {type(e).__name__}: {e}")
                        debug_logger.log_error_with_context(
                            f"EQ annotation exception: {type(e).__name__}: {e}",
                            track_id=track_id,
                            context={'file_path': file_path, 'error_type': type(e).__name__}
                        )
                        continue
                
                logger.info("🎛️ EQ annotation complete - ready for aggressive mix!")
                debug_logger.save_json_analysis()
                
                summary = debug_logger.get_summary()
                logger.info(f"📊 Debug logs saved:")
                logger.info(f"   - {summary['debug_log']}")
                logger.info(f"   - {summary['analysis_log']}")
                logger.info(f"   - {summary['filters_log']}")
            
            except ImportError:
                logger.warning("⚠️ DJ EQ modules not available, skipping EQ annotation")
            except Exception as e:
                logger.warning(f"⚠️ EQ annotation failed: {e}")
                if debug_logger:
                    debug_logger.log_error_with_context(f"Annotation phase failed: {e}")
        else:
            logger.info("🎛️ DJ EQ analysis DISABLED (EQ_ENABLED=false)")

        # 💾 Save updated transitions JSON with EQ annotations
        try:
            with open(transitions_json_path, "w") as f:
                json.dump(plan, f, indent=2)
            logger.debug(f"✅ Transitions JSON updated with EQ annotations: {transitions_json_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save updated transitions JSON: {e}")

        # Generate script
        script = _generate_liquidsoap_script_legacy(plan, output_path, self.config, playlist_m3u_path)
        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write and execute script
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".liq", mode="w", delete=False
            ) as tmp:
                tmp.write(script)
                script_path = tmp.name

            logger.debug(f"Liquidsoap script: {script_path}")
            logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")

            # Also save to a known location for debugging
            debug_script_path = Path("/tmp/last_render.liq")
            debug_script_path.write_text(script)
            logger.info(f"Debug script saved to: {debug_script_path}")

            # 🎵 FIX: Add ffmpeg: protocol wrapper for M4A files (ALAC support)
            script_with_alac_fix = script
            import re
            # Pattern 1: single("annotate:...:/path/to/file.m4a")
            script_with_alac_fix = re.sub(
                r'single\("annotate:([^"]+):/([^"]*\.m4a)"\)',
                r'single("annotate:\1:ffmpeg:/\2")',
                script_with_alac_fix
            )
            # Pattern 2: single("/path/to/file.m4a")
            script_with_alac_fix = re.sub(
                r'single\("(/[^"]*\.m4a)"\)',
                r'single("ffmpeg:\1")',
                script_with_alac_fix
            )
            
            # Write the patched script
            with open(script_path, 'w') as f:
                f.write(script_with_alac_fix)
            
            logger.info(f"✅ Applied ALAC/M4A FFmpeg wrapper to script")

            result = subprocess.run(
                ["liquidsoap", script_path],
                timeout=timeout_seconds,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"Liquidsoap failed with return code {result.returncode}")
                logger.error(f"Liquidsoap stderr: {result.stderr if result.stderr else '(no stderr)'}")
                logger.error(f"Liquidsoap stdout: {result.stdout if result.stdout else '(no stdout)'}")
                logger.error(f"Debug script saved to: {debug_script_path}")
                logger.error(f"You can inspect with: cat {debug_script_path}")
                _cleanup_partial_output(output_path)
                return False

            # Validate output
            if not _validate_output_file(output_path):
                logger.error("Output file validation failed")
                _cleanup_partial_output(output_path)
                return False

            # Add metadata to output
            playlist_id = plan.get("playlist_id", "autodj-playlist")
            timestamp = datetime.now().isoformat()
            _write_mix_metadata(output_path, playlist_id, timestamp, transitions=plan.get("transitions"))

            logger.info(f"✅ Render complete: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Render timeout after {timeout_seconds} seconds")
            _cleanup_partial_output(output_path)
            return False
        except Exception as e:
            logger.error(f"Render failed: {e}")
            _cleanup_partial_output(output_path)
            return False
        finally:
            # Cleanup temp script
            if script_path:
                try:
                    Path(script_path).unlink()
                    logger.debug(f"Cleaned up temp script: {script_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp script {script_path}: {e}")
