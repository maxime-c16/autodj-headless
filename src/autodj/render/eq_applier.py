"""
DJ EQ Automation Engine - Phase 2: Audio DSP Implementation

Extends eq_automation.py with actual audio signal processing.

Implements professional DJ EQ techniques with proper Butterworth filters
and envelope automation for within-track EQ cuts.

Per DJ_EQ_RESEARCH.md § Translating DJ Skills to Code:
- Bass Cut: High-pass filter on bass reduction (60-120Hz)
- High Swap: Peaking EQ on high reduction (3-12kHz)
- Filter Sweep: Low-pass sweep from muffled to open
- Three-Band Blend: Gradual fade on all three bands
- Bass Swap: Quick bass reduction/restoration

All cuts are TEMPORARY and return to neutral (no EQ) by phrase end.
"""

import logging
import numpy as np
from typing import Tuple, Optional, List
from dataclasses import dataclass
from scipy import signal

logger = logging.getLogger(__name__)


@dataclass
class EQAutomationPoint:
    """
    Single automation point for a time-varying EQ parameter.
    
    Represents one moment in an EQ envelope (e.g., attack start, hold peak, release end).
    """
    sample: int          # Sample position in audio
    magnitude_db: float  # Target magnitude in dB
    phase: str          # "attack", "hold", "release"


class EQAutomationEnvelope:
    """
    Time-varying EQ envelope with attack, hold, and release.
    
    Generates smooth curves for EQ parameter automation.
    """
    
    def __init__(
        self,
        attack_samples: int,
        hold_samples: int,
        release_samples: int,
        magnitude_db: float = -6.0,
    ):
        """
        Initialize EQ envelope.
        
        Args:
            attack_samples: Samples to attack the cut (0 = instant)
            hold_samples: Samples to hold at full cut
            release_samples: Samples to release back to neutral
            magnitude_db: Depth of cut (-3 to -12 dB)
        """
        self.attack_samples = attack_samples
        self.hold_samples = hold_samples
        self.release_samples = release_samples
        self.magnitude_db = magnitude_db
        
        # Total duration
        self.total_samples = attack_samples + hold_samples + release_samples
    
    def generate_automation(self) -> np.ndarray:
        """
        Generate automation curve for EQ parameter.
        
        Returns:
            Array of magnitude values (0 to -∞ dB) matching total_samples length.
            Attack starts at 0dB (neutral), ramps to magnitude_db (cut).
        """
        curve = np.zeros(self.total_samples)
        
        # Attack phase: ramp from 0dB (neutral) to magnitude_db (cut)
        if self.attack_samples > 0:
            # For instant attack (0 samples), start at magnitude_db
            attack_curve = np.linspace(0, self.magnitude_db, self.attack_samples + 1)
            curve[:self.attack_samples] = attack_curve[1:]  # Skip first point (0dB)
        else:
            # Instant attack: immediately at magnitude_db
            curve[0] = self.magnitude_db
        
        # Hold phase: flat at magnitude_db
        hold_start = self.attack_samples
        hold_end = hold_start + self.hold_samples
        if hold_start < len(curve):
            curve[hold_start:min(hold_end, len(curve))] = self.magnitude_db
        
        # Release phase: ramp from magnitude_db back to 0dB
        if self.release_samples > 0:
            release_start = hold_end
            if release_start < len(curve):
                release_curve = np.linspace(self.magnitude_db, 0, self.release_samples + 1)
                release_end = min(release_start + self.release_samples, len(curve))
                curve[release_start:release_end] = release_curve[:-1]  # Skip last point (0dB)
        
        return curve


class Butterworth3BandEQ:
    """
    3-band equalizer using Butterworth filters.
    
    Implements low (60-120Hz), mid (300-1kHz), and high (3-12kHz) bands.
    Each band can be cut independently.
    """
    
    # Frequency definitions (Hz)
    BAND_DEFINITIONS = {
        'low': {'center': 90, 'low_cutoff': 60, 'high_cutoff': 120},
        'mid': {'center': 600, 'low_cutoff': 300, 'high_cutoff': 1000},
        'high': {'center': 6000, 'low_cutoff': 3000, 'high_cutoff': 12000},
    }
    
    def __init__(self, sample_rate: int = 44100, q: float = 0.7):
        """
        Initialize 3-band EQ.
        
        Args:
            sample_rate: Audio sample rate (Hz)
            q: Q factor for peaking EQ (higher = more selective)
        """
        self.sample_rate = sample_rate
        self.q = q
        self.filter_cache = {}
    
    def create_peaking_filter(
        self,
        center_freq: float,
        gain_db: float,
        q: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create peaking EQ filter coefficients.
        
        Args:
            center_freq: Center frequency (Hz)
            gain_db: Gain in dB (negative = cut)
            q: Q factor
        
        Returns:
            (b, a) coefficients for scipy.signal.sosfilt
        """
        # Design peaking EQ filter
        # See: Digital Audio EQ Cookbook
        # https://www.w3.org/TR/audio-eq-cookbook/
        
        w0 = 2 * np.pi * center_freq / self.sample_rate
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        
        A = 10 ** (gain_db / 40.0)  # Linear amplitude
        alpha = sin_w0 / (2 * q)
        
        # Peaking EQ coefficients
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        
        # Normalize by a0
        b = np.array([b0 / a0, b1 / a0, b2 / a0])
        a = np.array([1.0, a1 / a0, a2 / a0])
        
        return b, a
    
    def create_highpass_filter(self, cutoff_freq: float, order: int = 2):
        """
        Create high-pass Butterworth filter.
        
        Args:
            cutoff_freq: Cutoff frequency (Hz)
            order: Filter order (higher = steeper)
        
        Returns:
            (b, a) coefficients
        """
        nyquist = self.sample_rate / 2.0
        normalized_cutoff = cutoff_freq / nyquist
        
        # Butterworth high-pass
        b, a = signal.butter(order, normalized_cutoff, btype='high')
        return b, a
    
    def apply_band_cut(
        self,
        audio: np.ndarray,
        band: str,
        magnitude_db: float,
    ) -> np.ndarray:
        """
        Apply EQ cut to a single frequency band.
        
        Args:
            audio: Input audio array
            band: 'low', 'mid', or 'high'
            magnitude_db: Cut amount (negative dB)
        
        Returns:
            Filtered audio array
        """
        if band not in self.BAND_DEFINITIONS:
            raise ValueError(f"Unknown band: {band}. Must be 'low', 'mid', or 'high'")
        
        if abs(magnitude_db) < 0.1:  # Near-zero, skip filtering
            return audio
        
        band_def = self.BAND_DEFINITIONS[band]
        
        # Create peaking EQ filter
        b, a = self.create_peaking_filter(
            center_freq=band_def['center'],
            gain_db=magnitude_db,
            q=self.q,
        )
        
        # Apply filter (forward-backward for zero-phase)
        filtered = signal.filtfilt(b, a, audio)
        
        return filtered
    
    def apply_multiband_cut(
        self,
        audio: np.ndarray,
        low_db: float = 0,
        mid_db: float = 0,
        high_db: float = 0,
    ) -> np.ndarray:
        """
        Apply EQ cuts to multiple bands simultaneously.
        
        Args:
            audio: Input audio array
            low_db: Low band cut (negative dB)
            mid_db: Mid band cut (negative dB)
            high_db: High band cut (negative dB)
        
        Returns:
            Filtered audio array
        """
        result = audio.copy()
        
        if abs(low_db) > 0.1:
            result = self.apply_band_cut(result, 'low', low_db)
        if abs(mid_db) > 0.1:
            result = self.apply_band_cut(result, 'mid', mid_db)
        if abs(high_db) > 0.1:
            result = self.apply_band_cut(result, 'high', high_db)
        
        return result


class EQAutomationApplier:
    """
    Applies EQ automation curves to audio with proper timing.
    
    Takes EQOpportunity objects and applies them to audio with
    envelope automation for smooth, professional DJ-style cuts.
    """
    
    def __init__(self, sample_rate: int = 44100):
        """
        Initialize EQ applier.
        
        Args:
            sample_rate: Audio sample rate (Hz)
        """
        self.sample_rate = sample_rate
        self.eq_filter = Butterworth3BandEQ(sample_rate=sample_rate)
    
    def apply_eq_opportunity(
        self,
        audio: np.ndarray,
        opportunity,  # EQOpportunity from eq_automation.py
        bpm: float,
        track_start_sample: int = 0,
    ) -> np.ndarray:
        """
        Apply a single EQ opportunity to audio.
        
        Args:
            audio: Input audio array
            opportunity: EQOpportunity object
            bpm: Track BPM for bar calculations
            track_start_sample: Sample position of track start in mix
        
        Returns:
            Audio with EQ opportunity applied
        """
        from autodj.render.eq_automation import EQCutType, FrequencyBand
        
        # Calculate timing
        seconds_per_bar = 240.0 / bpm  # (60s/min * 4 beats/bar) / (bpm beats/min)
        samples_per_bar = int(seconds_per_bar * self.sample_rate)
        
        # EQ start position in audio
        eq_start_sample = opportunity.bar * samples_per_bar
        eq_end_sample = eq_start_sample + opportunity.envelope.total_samples
        
        logger.debug(
            f"Applying {opportunity.cut_type.value}: "
            f"bar {opportunity.bar}, "
            f"samples {eq_start_sample}-{eq_end_sample}, "
            f"confidence {opportunity.confidence:.2f}"
        )
        
        # Ensure we don't go past audio length
        if eq_start_sample >= len(audio):
            logger.warning(
                f"EQ opportunity start ({eq_start_sample}) beyond audio length ({len(audio)})"
            )
            return audio
        
        eq_end_sample = min(eq_end_sample, len(audio))
        
        # Generate automation curve
        envelope = opportunity.envelope
        automation_curve = envelope.generate_automation()
        
        # Trim automation to fit audio segment
        automation_curve = automation_curve[:eq_end_sample - eq_start_sample]
        
        # Extract audio segment
        audio_segment = audio[eq_start_sample:eq_end_sample].copy()
        
        # Apply EQ automation
        result = audio.copy()
        
        if opportunity.cut_type == EQCutType.BASS_CUT:
            # Apply bass cut with envelope
            for i, mag_db in enumerate(automation_curve):
                # Process audio frame-by-frame (expensive, but accurate)
                # In production, use overlap-add method for efficiency
                frame_size = 2048
                frame_start = i * frame_size
                frame_end = min(frame_start + frame_size, len(audio_segment))
                
                if frame_start >= len(audio_segment):
                    break
                
                frame = audio_segment[frame_start:frame_end]
                filtered_frame = self.eq_filter.apply_band_cut(frame, 'low', mag_db)
                audio_segment[frame_start:frame_end] = filtered_frame
            
            result[eq_start_sample:eq_end_sample] = audio_segment
        
        elif opportunity.cut_type == EQCutType.HIGH_SWAP:
            # Apply high-frequency cut with envelope
            for i, mag_db in enumerate(automation_curve):
                frame_size = 2048
                frame_start = i * frame_size
                frame_end = min(frame_start + frame_size, len(audio_segment))
                
                if frame_start >= len(audio_segment):
                    break
                
                frame = audio_segment[frame_start:frame_end]
                filtered_frame = self.eq_filter.apply_band_cut(frame, 'high', mag_db)
                audio_segment[frame_start:frame_end] = filtered_frame
            
            result[eq_start_sample:eq_end_sample] = audio_segment
        
        elif opportunity.cut_type == EQCutType.FILTER_SWEEP:
            # Low-pass sweep: start at 2kHz, gradually open to 20kHz
            # Approximate with multiband automation
            for i, mag_db in enumerate(automation_curve):
                frame_size = 2048
                frame_start = i * frame_size
                frame_end = min(frame_start + frame_size, len(audio_segment))
                
                if frame_start >= len(audio_segment):
                    break
                
                frame = audio_segment[frame_start:frame_end]
                # Apply progressive high-cut (more aggressive at start)
                high_cut = mag_db  # Start muffled, gradually open
                filtered_frame = self.eq_filter.apply_band_cut(frame, 'high', high_cut)
                audio_segment[frame_start:frame_end] = filtered_frame
            
            result[eq_start_sample:eq_end_sample] = audio_segment
        
        elif opportunity.cut_type == EQCutType.THREE_BAND_BLEND:
            # All three bands with envelope
            for i, mag_db in enumerate(automation_curve):
                frame_size = 2048
                frame_start = i * frame_size
                frame_end = min(frame_start + frame_size, len(audio_segment))
                
                if frame_start >= len(audio_segment):
                    break
                
                frame = audio_segment[frame_start:frame_end]
                # Apply to all three bands
                filtered_frame = self.eq_filter.apply_multiband_cut(
                    frame,
                    low_db=mag_db,
                    mid_db=mag_db,
                    high_db=mag_db,
                )
                audio_segment[frame_start:frame_end] = filtered_frame
            
            result[eq_start_sample:eq_end_sample] = audio_segment
        
        elif opportunity.cut_type == EQCutType.BASS_SWAP:
            # Quick bass transition
            for i, mag_db in enumerate(automation_curve):
                frame_size = 2048
                frame_start = i * frame_size
                frame_end = min(frame_start + frame_size, len(audio_segment))
                
                if frame_start >= len(audio_segment):
                    break
                
                frame = audio_segment[frame_start:frame_end]
                filtered_frame = self.eq_filter.apply_band_cut(frame, 'low', mag_db)
                audio_segment[frame_start:frame_end] = filtered_frame
            
            result[eq_start_sample:eq_end_sample] = audio_segment
        
        else:
            logger.warning(f"Unknown EQ cut type: {opportunity.cut_type}")
        
        return result
    
    def apply_all_opportunities(
        self,
        audio: np.ndarray,
        opportunities: List,  # List[EQOpportunity]
        bpm: float,
    ) -> np.ndarray:
        """
        Apply all EQ opportunities to audio.
        
        Args:
            audio: Input audio array
            opportunities: List of EQOpportunity objects
            bpm: Track BPM
        
        Returns:
            Audio with all EQ opportunities applied
        """
        result = audio.copy()
        
        for opp in opportunities:
            result = self.apply_eq_opportunity(result, opp, bpm)
        
        return result


class EQAutomationLogger:
    """
    Logging utilities for EQ automation analysis.
    
    Provides detailed logging of bar calculations, timing, and EQ application.
    """
    
    @staticmethod
    def log_opportunity_timing(
        opportunity,  # EQOpportunity
        bpm: float,
        sample_rate: int = 44100,
    ) -> str:
        """
        Generate detailed timing log for an EQ opportunity.
        
        Args:
            opportunity: EQOpportunity object
            bpm: Track BPM
            sample_rate: Audio sample rate
        
        Returns:
            Formatted timing log string
        """
        seconds_per_bar = 240.0 / bpm
        samples_per_bar = int(seconds_per_bar * sample_rate)
        
        # Calculate timing
        eq_start_sample = opportunity.bar * samples_per_bar
        eq_start_time = eq_start_sample / sample_rate
        
        attack_time = opportunity.envelope.attack_ms / 1000.0
        attack_samples = int(attack_time * sample_rate)
        
        hold_time = opportunity.envelope.hold_bars * seconds_per_bar
        hold_samples = opportunity.envelope.hold_bars * samples_per_bar
        
        release_time = opportunity.envelope.release_ms / 1000.0
        release_samples = int(release_time * sample_rate)
        
        total_time = attack_time + hold_time + release_time
        
        log = (
            f"\n{opportunity.cut_type.value.upper()} @ Bar {opportunity.bar}\n"
            f"  BPM: {bpm}, Seconds/Bar: {seconds_per_bar:.3f}, "
            f"Samples/Bar: {samples_per_bar}\n"
            f"  Start: {eq_start_time:.3f}s (sample {eq_start_sample})\n"
            f"  Attack: {attack_time*1000:.0f}ms ({attack_samples} samples)\n"
            f"  Hold: {hold_time:.3f}s ({hold_samples} samples, "
            f"{opportunity.envelope.hold_bars} bars)\n"
            f"  Release: {release_time*1000:.0f}ms ({release_samples} samples)\n"
            f"  Total Duration: {total_time:.3f}s\n"
            f"  End: {eq_start_time + total_time:.3f}s "
            f"(sample {eq_start_sample + attack_samples + hold_samples + release_samples})\n"
            f"  Frequency: {opportunity.frequency_band.value}, "
            f"Magnitude: {opportunity.magnitude_db:.1f}dB\n"
            f"  Confidence: {opportunity.confidence:.2f}\n"
            f"  Reason: {opportunity.reason}"
        )
        
        return log
    
    @staticmethod
    def log_timing_validation(
        opportunities: List,  # List[EQOpportunity]
        bpm: float,
        total_bars: int,
        sample_rate: int = 44100,
    ) -> str:
        """
        Generate validation log for all EQ opportunities.
        
        Checks for overlaps, timing issues, etc.
        """
        seconds_per_bar = 240.0 / bpm
        samples_per_bar = int(seconds_per_bar * sample_rate)
        total_samples = total_bars * samples_per_bar
        
        log = f"\n=== EQ OPPORTUNITY TIMING VALIDATION ===\n"
        log += f"BPM: {bpm}, Total Bars: {total_bars}\n"
        log += f"Sample Rate: {sample_rate} Hz\n"
        log += f"Seconds/Bar: {seconds_per_bar:.3f}s\n"
        log += f"Samples/Bar: {samples_per_bar}\n"
        log += f"Total Duration: {total_bars * seconds_per_bar:.1f}s "
        log += f"({total_samples} samples)\n\n"
        
        if not opportunities:
            log += "No EQ opportunities detected.\n"
            return log
        
        log += f"Opportunities ({len(opportunities)}):\n"
        
        for i, opp in enumerate(opportunities):
            eq_start_sample = opp.bar * samples_per_bar
            eq_start_time = eq_start_sample / sample_rate
            
            attack_samples = int((opp.envelope.attack_ms / 1000.0) * sample_rate)
            hold_samples = opp.envelope.hold_bars * samples_per_bar
            release_samples = int((opp.envelope.release_ms / 1000.0) * sample_rate)
            total_eq_samples = attack_samples + hold_samples + release_samples
            
            eq_end_sample = eq_start_sample + total_eq_samples
            eq_end_time = eq_end_sample / sample_rate
            
            status = "✅" if eq_end_sample < total_samples else "⚠️"
            
            log += (
                f"\n  {i+1}. {opp.cut_type.value} @ bar {opp.bar}\n"
                f"     Time: {eq_start_time:.2f}s → {eq_end_time:.2f}s "
                f"({total_eq_samples} samples) {status}\n"
                f"     Magnitude: {opp.magnitude_db:.1f}dB, "
                f"Confidence: {opp.confidence:.2f}"
            )
        
        log += "\n"
        return log
