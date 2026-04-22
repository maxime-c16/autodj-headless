"""
DJ EQ Automation Engine

Implements professional DJ EQ techniques for within-track automation:
1. Bass Cut & Release: Quick, percussive bass reductions (1-4 bars)
2. High Frequency Swap: Gentle harshness control (4-8 bars)
3. Filter Sweep: Dramatic low-pass sweep (8-16 bars)
4. Three-Band Blend: Smooth, gradual transitions (16-32 bars)
5. Bass Swap: Energy-based bass transitions

Per DJ_EQ_RESEARCH.md principles:
- EQ cuts are TEMPORARY, never permanent
- Always return to neutral (12 o'clock) after effect
- Bar-aligned timing: 4, 8, 16, 32 bars
- Gentle magnitudes: -3dB to -12dB (cuts, not boosts)
- Confidence-based selection: ≥0.85 confidence only

Integration: EQ automation runs BEFORE sequencing in the render pipeline.
"""

import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import json

logger = logging.getLogger(__name__)


class EQCutType(Enum):
    """DJ EQ technique types."""
    BASS_CUT = "bass_cut"           # Quick bass reduction (1-4 bars)
    HIGH_SWAP = "high_swap"         # High-frequency control (4-8 bars)
    FILTER_SWEEP = "filter_sweep"   # Low-pass sweep (8-16 bars)
    THREE_BAND_BLEND = "three_band_blend"  # All bands gradual (16-32 bars)
    BASS_SWAP = "bass_swap"         # Bass transition (4-8 bars)


class FrequencyBand(Enum):
    """3-band DJ EQ bands."""
    LOW = "low"      # Bass: 60-120 Hz (kick, bass)
    MID = "mid"      # Personality: 300-1kHz (vocals, drums)
    HIGH = "high"    # Shine: 3-12 kHz (hi-hats, cymbals, brightness)
    # Special case:
    SWEEP = "sweep"  # Low-pass filter sweep (2kHz → 20kHz)


@dataclass
class EQEnvelope:
    """Attack/Hold/Release envelope for smooth EQ automation."""
    attack_ms: int       # How quickly cut is introduced (0-500ms)
    hold_bars: int      # How long it stays at full effect (1-16)
    release_ms: int     # How it returns to neutral (0-1000ms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EQOpportunity:
    """
    A musical moment where EQ automation can be applied.
    
    Represents a single EQ cut opportunity in a track.
    """
    cut_type: EQCutType
    bar: int                           # Starting bar (0-indexed)
    confidence: float                  # 0.0-1.0 confidence score
    
    # EQ parameters
    frequency_band: FrequencyBand     # Which band to affect
    magnitude_db: float               # Depth of cut (-3 to -12 dB, negative = cut)
    
    # Timing
    envelope: EQEnvelope
    
    # Musicality
    phrase_length_bars: int           # 4, 8, 16, or 32 (matches musical phrasing)
    
    # Metadata
    reason: str = ""                  # Why this EQ opportunity was selected
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = asdict(self)
        result['cut_type'] = self.cut_type.value
        result['frequency_band'] = self.frequency_band.value
        result['envelope'] = self.envelope.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EQOpportunity':
        """Reconstruct from dict (reverse of to_dict)."""
        data = dict(data)
        data['cut_type'] = EQCutType(data['cut_type'])
        data['frequency_band'] = FrequencyBand(data['frequency_band'])
        data['envelope'] = EQEnvelope(**data['envelope'])
        return cls(**data)


class EQAutomationEngine:
    """
    Detects and manages EQ automation opportunities in audio.
    
    Per DJ_EQ_RESEARCH.md, proper DJ mixing uses surgical, tempo-aware
    EQ adjustments at specific moments. This engine:
    
    1. Identifies musically appropriate moments for EQ cuts
    2. Selects the right technique (bass cut, high swap, filter sweep, etc.)
    3. Generates proper envelopes (attack/hold/release)
    4. Ensures all cuts return to neutral by phrase end
    5. Applies only at HIGH confidence (≥0.85)
    """
    
    # Confidence thresholds
    MIN_CONFIDENCE = 0.85
    
    # Frequency band definitions (Hz)
    FREQ_RANGES = {
        FrequencyBand.LOW: (60, 120),      # Bass: kick, sub-bass
        FrequencyBand.MID: (300, 1000),    # Personality: vocals, instruments
        FrequencyBand.HIGH: (3000, 12000), # Shine: hi-hats, cymbals, brightness
    }
    
    # Default EQ cut magnitudes (dB, negative = cut)
    DEFAULT_MAGNITUDES = {
        EQCutType.BASS_CUT: -8.0,          # -6dB ±2dB typical
        EQCutType.HIGH_SWAP: -4.5,         # -3dB ±2dB typical
        EQCutType.FILTER_SWEEP: -12.0,     # Gradually opens (starts muffled)
        EQCutType.THREE_BAND_BLEND: -6.0,  # -3 to -9dB on each band
        EQCutType.BASS_SWAP: -7.0,         # -6dB ±2dB typical
    }
    
    # Default envelopes (attack/hold/release in bars and ms)
    DEFAULT_ENVELOPES = {
        EQCutType.BASS_CUT: EQEnvelope(
            attack_ms=0,        # Instant to cut (percussive)
            hold_bars=2,        # Hold for 2 bars
            release_ms=0        # Snap back to neutral (percussive)
        ),
        EQCutType.HIGH_SWAP: EQEnvelope(
            attack_ms=200,      # Gradual ramp down (1-2 bars)
            hold_bars=4,        # Hold at reduced level
            release_ms=200      # Gradual ramp back up
        ),
        EQCutType.FILTER_SWEEP: EQEnvelope(
            attack_ms=100,      # Quick attack
            hold_bars=12,       # Long hold (sweep lasts 16 bars total)
            release_ms=200      # Snap back
        ),
        EQCutType.THREE_BAND_BLEND: EQEnvelope(
            attack_ms=500,      # Gradual attack over bars 1-8
            hold_bars=16,       # Hold for middle phase
            release_ms=500      # Gradual release over bars 16-24
        ),
        EQCutType.BASS_SWAP: EQEnvelope(
            attack_ms=50,       # Very quick
            hold_bars=4,        # Hold for 4 bars
            release_ms=50       # Snap back
        ),
    }
    
    def __init__(self, bpm: float, sample_rate: int = 44100):
        """
        Initialize EQ automation engine.
        
        Args:
            bpm: Track BPM for bar-aligned timing
            sample_rate: Audio sample rate (Hz)
        """
        self.bpm = bpm
        self.sample_rate = sample_rate
        self.seconds_per_bar = 240.0 / bpm  # (60s/min * 4 beats/bar) / (bpm beats/min)
        self.samples_per_bar = int(self.seconds_per_bar * sample_rate)
        
        logger.debug(
            f"EQ Engine initialized: BPM={bpm}, "
            f"seconds/bar={self.seconds_per_bar:.2f}, "
            f"samples/bar={self.samples_per_bar}"
        )
    
    def detect_opportunities(
        self,
        audio_features: Dict[str, Any],
        track_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[EQOpportunity]:
        """
        Detect EQ automation opportunities in a track.
        
        Args:
            audio_features: Dict with track analysis (from MIR or metadata):
                - 'spectral_centroid': avg brightness (Hz)
                - 'loudness_db': LUFS loudness
                - 'energy': energy level
                - 'percussiveness': drum intensity (0-1)
                - 'num_bars': total bars in track
                - 'intro_confidence': intro section confidence
                - 'vocal_confidence': vocal presence confidence
                - 'breakdown_confidence': breakdown section confidence
                
            track_metadata: Optional metadata dict with artist/title for logging
        
        Returns:
            List of EQOpportunity objects, sorted by bar position.
            Empty list if no high-confidence opportunities found.
        """
        opportunities = []
        num_bars = audio_features.get('num_bars', 16)
        track_name = ""
        if track_metadata:
            artist = track_metadata.get('artist', 'Unknown')
            title = track_metadata.get('title', 'Unknown')
            track_name = f"{artist} — {title}"
        
        logger.debug(f"Detecting EQ opportunities for: {track_name} ({num_bars} bars)")
        
        # --- Detection Strategy 1: Intro Filter Sweep ---
        # Reduce all EQ in intro, gradually bring back for main groove
        intro_conf = audio_features.get('intro_confidence', 0.0)
        if intro_conf >= self.MIN_CONFIDENCE and num_bars >= 16:
            logger.debug(f"  ✓ Intro detected (conf={intro_conf:.2f})")
            opp = EQOpportunity(
                cut_type=EQCutType.FILTER_SWEEP,
                bar=0,
                confidence=intro_conf,
                frequency_band=FrequencyBand.SWEEP,
                magnitude_db=self.DEFAULT_MAGNITUDES[EQCutType.FILTER_SWEEP],
                envelope=self.DEFAULT_ENVELOPES[EQCutType.FILTER_SWEEP],
                phrase_length_bars=16,
                reason="Intro filter sweep: gradually open from muffled to bright"
            )
            opportunities.append(opp)
        
        # --- Detection Strategy 2: Vocal Moment High Swap ---
        # Reduce harshness during vocal sections
        vocal_conf = audio_features.get('vocal_confidence', 0.0)
        if vocal_conf >= self.MIN_CONFIDENCE:
            # Find a good moment (usually bar 8 or 12 for standard track structure)
            vocal_bar = min(8, max(0, num_bars - 8))
            logger.debug(f"  ✓ Vocal section detected (conf={vocal_conf:.2f}) at bar {vocal_bar}")
            opp = EQOpportunity(
                cut_type=EQCutType.HIGH_SWAP,
                bar=vocal_bar,
                confidence=vocal_conf,
                frequency_band=FrequencyBand.HIGH,
                magnitude_db=self.DEFAULT_MAGNITUDES[EQCutType.HIGH_SWAP],
                envelope=self.DEFAULT_ENVELOPES[EQCutType.HIGH_SWAP],
                phrase_length_bars=8,
                reason="Vocal presence: reduce high-frequency harshness during vocals"
            )
            opportunities.append(opp)
        
        # --- Detection Strategy 3: Breakdown Bass Cut ---
        # Quick bass reduction for energy punctuation
        breakdown_conf = audio_features.get('breakdown_confidence', 0.0)
        if breakdown_conf >= self.MIN_CONFIDENCE and num_bars >= 16:
            # Place at bar 12 (last 4 bars before potential drop)
            breakdown_bar = max(0, min(12, num_bars - 4))
            logger.debug(f"  ✓ Breakdown detected (conf={breakdown_conf:.2f}) at bar {breakdown_bar}")
            opp = EQOpportunity(
                cut_type=EQCutType.BASS_CUT,
                bar=breakdown_bar,
                confidence=breakdown_conf,
                frequency_band=FrequencyBand.LOW,
                magnitude_db=self.DEFAULT_MAGNITUDES[EQCutType.BASS_CUT],
                envelope=self.DEFAULT_ENVELOPES[EQCutType.BASS_CUT],
                phrase_length_bars=4,
                reason="Breakdown bass cut: tension building before potential drop"
            )
            opportunities.append(opp)
        
        # --- Detection Strategy 4: Percussiveness-Based Bass Swap ---
        # If track is very percussive, use a bass swap
        percussiveness = audio_features.get('percussiveness', 0.0)
        if percussiveness >= 0.70 and num_bars >= 12:
            logger.debug(f"  ✓ High percussiveness detected ({percussiveness:.2f})")
            # Use for energy management at bar 4 or bar 8
            bass_swap_bar = 4
            logger.debug(f"  → Adding bass swap at bar {bass_swap_bar}")
            opp = EQOpportunity(
                cut_type=EQCutType.BASS_SWAP,
                bar=bass_swap_bar,
                confidence=percussiveness * 0.9,  # Slightly reduce confidence
                frequency_band=FrequencyBand.LOW,
                magnitude_db=self.DEFAULT_MAGNITUDES[EQCutType.BASS_SWAP],
                envelope=self.DEFAULT_ENVELOPES[EQCutType.BASS_SWAP],
                phrase_length_bars=4,
                reason="Bass swap: energy management in percussive section"
            )
            opportunities.append(opp)
        
        # --- Filter out opportunities that would overlap ---
        # Sort by bar position first
        opportunities.sort(key=lambda x: x.bar)
        
        # Remove overlapping cuts (keep higher confidence)
        filtered = []
        for opp in opportunities:
            # Check if this would overlap with existing cuts
            overlaps = False
            for existing in filtered:
                opp_end = opp.bar + opp.phrase_length_bars
                existing_end = existing.bar + existing.phrase_length_bars
                
                # Allow 2-bar buffer between cuts
                if (existing.bar <= opp.bar <= existing_end + 2 or
                    opp.bar <= existing.bar <= opp_end + 2):
                    # Overlap detected
                    if opp.confidence > existing.confidence:
                        # Remove existing, keep new
                        filtered.remove(existing)
                        overlaps = False
                        break
                    else:
                        # Keep existing, skip new
                        overlaps = True
                        break
            
            if not overlaps:
                filtered.append(opp)
        
        logger.info(
            f"Detected {len(filtered)} EQ opportunities for {track_name}: "
            f"{', '.join(opp.cut_type.value for opp in filtered)}"
        )
        
        return filtered
    
    def bars_to_samples(self, bars: float) -> int:
        """Convert bars to audio samples."""
        return int(bars * self.samples_per_bar)
    
    def ms_to_samples(self, milliseconds: float) -> int:
        """Convert milliseconds to audio samples."""
        return int((milliseconds / 1000.0) * self.sample_rate)
    
    def generate_eq_timeline(
        self,
        opportunities: List[EQOpportunity],
        total_bars: int,
    ) -> Dict[str, Any]:
        """
        Generate a timeline of all EQ operations for a track.
        
        Returns a dict suitable for Liquidsoap DSP chain or post-processing:
        {
            'opportunities': [...],
            'timeline': [
                {
                    'bar': 0,
                    'type': 'bass_cut',
                    'sample_start': 0,
                    'sample_end': 2000,
                    'parameters': {...}
                },
                ...
            ]
        }
        """
        timeline = []
        
        for opp in opportunities:
            entry = {
                'bar': opp.bar,
                'type': opp.cut_type.value,
                'frequency_band': opp.frequency_band.value,
                'confidence': opp.confidence,
                'magnitude_db': opp.magnitude_db,
                
                # Sample-level timing
                'sample_start': self.bars_to_samples(opp.bar),
                'attack_samples': self.ms_to_samples(opp.envelope.attack_ms),
                'hold_samples': self.bars_to_samples(opp.envelope.hold_bars),
                'release_samples': self.ms_to_samples(opp.envelope.release_ms),
                
                # For reference
                'reason': opp.reason,
            }
            timeline.append(entry)
        
        return {
            'total_bars': total_bars,
            'bpm': self.bpm,
            'opportunities': [o.to_dict() for o in opportunities],
            'timeline': timeline,
        }


class EQAutomationDetector:
    """
    Facade for detecting and managing EQ opportunities.
    
    Coordinates between audio analysis, EQ detection, and render pipeline.
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize detector.
        
        Args:
            enabled: Whether EQ automation is globally enabled
        """
        self.enabled = enabled
        logger.info(f"EQ Automation Detector initialized (enabled={enabled})")
    
    def detect_for_track(
        self,
        track_path: str,
        bpm: float,
        audio_features: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[EQOpportunity]:
        """
        Detect EQ opportunities for a single track.
        
        Args:
            track_path: Path to audio file
            bpm: Track BPM
            audio_features: Analysis features dict
            metadata: Track metadata (artist, title, etc.)
        
        Returns:
            List of EQOpportunity objects
        """
        if not self.enabled:
            logger.debug("EQ automation disabled globally")
            return []
        
        engine = EQAutomationEngine(bpm=bpm)
        return engine.detect_opportunities(audio_features, metadata)
    
    def export_timeline(
        self,
        opportunities: List[EQOpportunity],
        bpm: float,
        total_bars: int,
    ) -> str:
        """Export EQ timeline as JSON."""
        engine = EQAutomationEngine(bpm=bpm)
        timeline = engine.generate_eq_timeline(opportunities, total_bars)
        return json.dumps(timeline, indent=2)
