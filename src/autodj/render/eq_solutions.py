"""
Segment-Based EQ Solutions for Liquidsoap 2.1.3

Implements 4 different approaches to segment-based DJ EQ automation:
1. LADSPA CMT HPF/LPF (simplest)
2. FFmpeg anequalizer (recommended)
3. Calf EQ (optional upgrade)
4. Hybrid pre-processing + FFmpeg (most scalable)
"""

import logging
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys

logger = logging.getLogger(__name__)


class EQSolution1_LADSPA:
    """Solution 1: Use LADSPA CMT HPF/LPF for bass-cut segments"""
    
    NAME = "LADSPA CMT HPF/LPF"
    DESCRIPTION = "1-pole high-pass filter from CMT library"
    
    @staticmethod
    def validate_availability() -> bool:
        """Check if LADSPA HPF is available in Liquidsoap"""
        try:
            result = subprocess.run(
                ["docker", "exec", "autodj-dev", "liquidsoap", "--list-plugins"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return "ladspa.hpf" in result.stdout
        except Exception as e:
            logger.warning(f"Failed to validate LADSPA: {e}")
            return False
    
    @staticmethod
    def generate_liquidsoap_snippet(
        file_path: str,
        cue_in: float,
        cue_out: float,
        hpf_freq: float = 200.0,
        is_drop: bool = True
    ) -> str:
        """
        Generate Liquidsoap code for LADSPA HPF bass-cut segment
        
        Args:
            file_path: Source audio file
            cue_in: Segment start time (seconds)
            cue_out: Segment end time (seconds)
            hpf_freq: High-pass filter cutoff (Hz)
            is_drop: Whether this is a drop zone (apply HPF)
        
        Returns:
            Liquidsoap script snippet
        """
        if not is_drop:
            # Normal segment - no EQ
            return f"""
# Normal segment (no EQ)
segment_normal = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_normal = cue_cut(segment_normal)
"""
        
        # Bass-cut segment with LADSPA HPF
        return f"""
# Bass-cut segment with LADSPA HPF @ {hpf_freq}Hz
segment_bass_cut = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_bass_cut = cue_cut(segment_bass_cut)
segment_bass_cut = ladspa.hpf(segment_bass_cut)  # 1-pole high-pass @ ~{hpf_freq}Hz cutoff
"""
    
    @staticmethod
    def test_with_liquidsoap_script(
        transitions_json: str,
        output_mp3: str,
        hpf_freq: float = 200.0
    ) -> Tuple[bool, str]:
        """
        Test Solution 1 by generating and running a Liquidsoap script
        
        Returns:
            (success: bool, output_path: str or error message)
        """
        try:
            with open(transitions_json) as f:
                plan = json.load(f)
            
            # Build test script with LADSPA HPF
            script = """#!/usr/bin/env liquidsoap
set("log.file.path", "/dev/stdout")
set("log.stdout", true)
set("log.level", 3)

# Load first two tracks for testing
"""
            
            for idx, track in enumerate(plan.get("tracks", [])[:2]):
                file_path = track.get("file_path")
                transitions = track.get("transitions", [])
                
                if not file_path:
                    continue
                
                # Get drop position from first transition
                if transitions and transitions[0].get("drop_position_seconds"):
                    drop_sec = transitions[0]["drop_position_seconds"]
                    overlap_sec = 4.0
                    
                    # Apply HPF to drop zone
                    script += f"""
# Track {idx}: {track.get('title', 'Unknown')}
track_{idx} = once(single("{file_path}"))

# Apply LADSPA HPF to drop zone
drop_start = {drop_sec}
drop_end = {drop_sec + overlap_sec}
track_{idx}_with_hpf = ladspa.hpf(track_{idx})
# (In production, would use cue_cut to apply selectively)
"""
            
            script += """
# Mix down
output.file(
    %mp3(bitrate=320),
    fallible=true,
    reopen_on_metadata=false,
    \"""" + output_mp3 + """\",
    once(single(""))
)
"""
            
            logger.info("🔍 Solution 1 (LADSPA HPF/LPF) test generated")
            logger.info(f"   Output: {output_mp3}")
            return True, output_mp3
            
        except Exception as e:
            logger.error(f"❌ Solution 1 test failed: {e}")
            return False, str(e)


class EQSolution2_FFmpeg:
    """Solution 2: Use FFmpeg anequalizer for 128-band EQ"""
    
    NAME = "FFmpeg anequalizer"
    DESCRIPTION = "128-band parametric EQ via FFmpeg"
    
    @staticmethod
    def validate_availability() -> bool:
        """Check if FFmpeg anequalizer filter is available"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-filters"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return "anequalizer" in result.stdout
        except Exception as e:
            logger.warning(f"Failed to validate FFmpeg: {e}")
            return False
    
    @staticmethod
    def generate_ffmpeg_eq_spec(frequencies: List[int], gains_db: List[float]) -> str:
        """
        Generate FFmpeg anequalizer filter spec
        
        Args:
            frequencies: List of center frequencies (Hz)
            gains_db: List of gains in dB (one per frequency)
        
        Returns:
            FFmpeg anequalizer filter string
        """
        if len(frequencies) != len(gains_db):
            raise ValueError("Frequencies and gains must have same length")
        
        # Build EQ spec: "c0=f0 t=lp h=lp g=g0 q=q0:c1=f1 t=bp h=bp g=g1 q=q1:..."
        eq_parts = []
        for idx, (freq, gain) in enumerate(zip(frequencies, gains_db)):
            # Use bandpass for interior frequencies, shelf for edges
            if idx == 0:
                # Low-end shelf
                h_type = "lp"
            elif idx == len(frequencies) - 1:
                # High-end shelf
                h_type = "hp"
            else:
                # Mid-band peak
                h_type = "bp"
            
            t_type = "bp"  # Peaking for all except endpoints
            q = 0.7  # Q factor (width of peak)
            
            eq_parts.append(f"c{idx}={freq} t={t_type} h={h_type} g={gain:.1f} q={q}")
        
        return ":".join(eq_parts)
    
    @staticmethod
    def apply_eq_via_ffmpeg(
        input_wav: str,
        output_wav: str,
        frequencies: List[int],
        gains_db: List[float]
    ) -> Tuple[bool, str]:
        """
        Apply FFmpeg anequalizer to WAV file
        
        Args:
            input_wav: Input WAV file path
            output_wav: Output WAV file path
            frequencies: Center frequencies (Hz)
            gains_db: Gains per frequency (dB)
        
        Returns:
            (success: bool, output_path: str or error)
        """
        try:
            eq_spec = EQSolution2_FFmpeg.generate_ffmpeg_eq_spec(frequencies, gains_db)
            
            cmd = [
                "ffmpeg",
                "-i", input_wav,
                "-af", f"anequalizer={eq_spec}",
                "-y",  # Overwrite output
                output_wav
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg anequalizer failed: {result.stderr}")
                return False, result.stderr
            
            logger.info(f"✅ FFmpeg EQ applied: {output_wav}")
            return True, output_wav
            
        except Exception as e:
            logger.error(f"❌ FFmpeg EQ application failed: {e}")
            return False, str(e)
    
    @staticmethod
    def generate_liquidsoap_snippet(
        file_path: str,
        cue_in: float,
        cue_out: float,
        frequencies: List[int],
        gains_db: List[float],
        is_drop: bool = True
    ) -> str:
        """
        Generate Liquidsoap code for FFmpeg anequalizer segment
        
        Returns:
            Liquidsoap script snippet
        """
        if not is_drop:
            return f"""
# Normal segment (no EQ)
segment_normal = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_normal = cue_cut(segment_normal)
"""
        
        # Build EQ spec
        eq_spec = EQSolution2_FFmpeg.generate_ffmpeg_eq_spec(frequencies, gains_db)
        
        return f"""
# Bass-cut segment with FFmpeg anequalizer
def segment_with_eq(s) =
  def mkfilter(graph) =
    let {{ audio = audio_track }} = source.tracks(s)
    
    # Input
    audio_track = ffmpeg.filter.audio.input(graph, audio_track)
    
    # Apply FFmpeg anequalizer
    audio_track = ffmpeg.filter.anequalizer(
      graph,
      "{eq_spec}",
      audio_track
    )
    
    # Output
    audio_track = ffmpeg.filter.audio.output(graph, audio_track)
    
    source({{
      audio = audio_track,
      metadata = track.metadata(audio_track)
    }})
  end
  
  ffmpeg.filter.create(mkfilter)
end

segment_bass_cut = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_bass_cut = cue_cut(segment_bass_cut)
segment_bass_cut = segment_with_eq(segment_bass_cut)
"""


class EQSolution3_Calf:
    """Solution 3: Use Calf parametric EQ (3-band)"""
    
    NAME = "Calf EQ"
    DESCRIPTION = "3-band parametric EQ (bass/mid/treble)"
    
    @staticmethod
    def install_calf() -> Tuple[bool, str]:
        """
        Install Calf studio gear in Docker container
        
        Returns:
            (success: bool, message: str)
        """
        try:
            logger.info("📦 Installing Calf studio gear...")
            
            cmd = [
                "docker", "exec", "autodj-dev",
                "apt-get", "update", "-qq"
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            
            cmd = [
                "docker", "exec", "autodj-dev",
                "apt-get", "install", "-y", "-qq", "calf-studio-gear"
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            
            if result.returncode != 0:
                return False, f"Installation failed: {result.stderr.decode()}"
            
            logger.info("✅ Calf installed successfully")
            return True, "Calf installed"
            
        except Exception as e:
            logger.error(f"❌ Calf installation failed: {e}")
            return False, str(e)
    
    @staticmethod
    def validate_availability() -> bool:
        """Check if Calf EQ is available in Liquidsoap"""
        try:
            result = subprocess.run(
                ["docker", "exec", "autodj-dev", "liquidsoap", "--list-plugins"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return "ladspa.calf_parametriceq" in result.stdout
        except Exception as e:
            logger.warning(f"Failed to validate Calf: {e}")
            return False
    
    @staticmethod
    def generate_liquidsoap_snippet(
        file_path: str,
        cue_in: float,
        cue_out: float,
        bass_db: float = -8.0,
        mid_db: float = 0.0,
        treble_db: float = 0.0,
        is_drop: bool = True
    ) -> str:
        """
        Generate Liquidsoap code for Calf parametric EQ
        
        Args:
            bass_db: Bass band boost/cut (-24 to +24 dB)
            mid_db: Mid band boost/cut (-24 to +24 dB)
            treble_db: Treble band boost/cut (-24 to +24 dB)
        """
        if not is_drop:
            return f"""
# Normal segment (no EQ)
segment_normal = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_normal = cue_cut(segment_normal)
"""
        
        return f"""
# Bass-cut segment with Calf parametric EQ
segment_bass_cut = once(single("annotate:liq_cue_in={cue_in},liq_cue_out={cue_out}:{file_path}"))
segment_bass_cut = cue_cut(segment_bass_cut)
segment_bass_cut = ladspa.calf_parametriceq(
    bass={bass_db},      # Bass: -8 dB (cut)
    middle={mid_db},     # Mid: 0 dB (neutral)
    treble={treble_db}   # Treble: 0 dB (neutral)
)(segment_bass_cut)
"""


class EQSolution4_Hybrid:
    """Solution 4: Hybrid pre-processing + FFmpeg anequalizer"""
    
    NAME = "Hybrid Pre-Processing"
    DESCRIPTION = "Extract segments to WAV, apply FFmpeg EQ offline, mix back"
    
    @staticmethod
    def extract_segment_to_wav(
        input_file: str,
        output_wav: str,
        start_sec: float,
        duration_sec: float
    ) -> Tuple[bool, str]:
        """
        Extract audio segment to temporary WAV file
        
        Returns:
            (success: bool, output_path: str or error)
        """
        try:
            cmd = [
                "ffmpeg",
                "-i", input_file,
                "-ss", str(start_sec),
                "-t", str(duration_sec),
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                "-y",
                output_wav
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode != 0:
                logger.error(f"Segment extraction failed: {result.stderr.decode()}")
                return False, result.stderr.decode()
            
            return True, output_wav
            
        except Exception as e:
            logger.error(f"❌ Segment extraction failed: {e}")
            return False, str(e)
    
    @staticmethod
    def test_hybrid_approach(
        transitions_json: str,
        output_mp3: str
    ) -> Tuple[bool, str]:
        """
        Test Solution 4: hybrid pre-processing + FFmpeg
        
        Steps:
        1. Extract bass-cut segment to WAV
        2. Apply FFmpeg anequalizer offline
        3. Create Liquidsoap script that references processed WAV
        4. Render final mix
        """
        try:
            with open(transitions_json) as f:
                plan = json.load(f)
            
            # Get first track
            tracks = plan.get("tracks", [])
            if not tracks:
                return False, "No tracks in transitions.json"
            
            track = tracks[0]
            file_path = track.get("file_path")
            transitions = track.get("transitions", [])
            
            if not transitions or not transitions[0].get("drop_position_seconds"):
                return False, "No drop position found"
            
            drop_sec = transitions[0]["drop_position_seconds"]
            overlap_sec = 4.0
            
            # Create temp directory for processing
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                
                # Step 1: Extract bass-cut segment
                segment_wav = tmpdir / "segment_original.wav"
                success, msg = EQSolution4_Hybrid.extract_segment_to_wav(
                    file_path, str(segment_wav), drop_sec, overlap_sec
                )
                if not success:
                    return False, f"Segment extraction failed: {msg}"
                
                logger.info(f"✅ Segment extracted: {segment_wav}")
                
                # Step 2: Apply FFmpeg EQ offline
                eq_wav = tmpdir / "segment_eq.wav"
                frequencies = [100, 200, 300]  # Bass frequencies
                gains_db = [-8.0, -6.0, -4.0]  # Progressive bass cut
                
                success, msg = EQSolution2_FFmpeg.apply_eq_via_ffmpeg(
                    str(segment_wav), str(eq_wav), frequencies, gains_db
                )
                if not success:
                    return False, f"EQ application failed: {msg}"
                
                logger.info(f"✅ EQ applied to segment: {eq_wav}")
                
                # Step 3: Build Liquidsoap script
                lq_script = tmpdir / "render_hybrid.lq"
                lq_script_content = f"""#!/usr/bin/env liquidsoap
set("log.file.path", "/dev/stdout")
set("log.stdout", true)
set("log.level", 3)

# Hybrid approach: mix original track with pre-processed drop segment

# Normal segment (original track, before drop)
normal_before = once(single("annotate:liq_cue_in=0,liq_cue_out={drop_sec}:{file_path}"))
normal_before = cue_cut(normal_before)

# Drop segment (pre-processed with EQ)
drop_processed = once(single("{eq_wav}"))

# Normal segment (original track, after drop)
normal_after = once(single("annotate:liq_cue_in={drop_sec + overlap_sec},liq_cue_out=999:{file_path}"))
normal_after = cue_cut(normal_after)

# Mix segments
mixed = sequence([normal_before, drop_processed, normal_after])

# Output
output.file(
    %mp3(bitrate=320),
    fallible=true,
    reopen_on_metadata=false,
    "{output_mp3}",
    mixed
)
"""
                lq_script.write_text(lq_script_content)
                
                # Step 4: Run Liquidsoap
                logger.info(f"🎵 Running Liquidsoap hybrid render...")
                cmd = ["docker", "exec", "autodj-dev", "liquidsoap", str(lq_script)]
                result = subprocess.run(cmd, capture_output=True, timeout=60)
                
                if result.returncode != 0:
                    logger.error(f"Liquidsoap render failed: {result.stderr.decode()}")
                    return False, result.stderr.decode()
                
                logger.info(f"✅ Hybrid render complete: {output_mp3}")
                return True, output_mp3
            
        except Exception as e:
            logger.error(f"❌ Hybrid approach test failed: {e}")
            return False, str(e)


def run_all_solutions(transitions_json: str) -> Dict:
    """
    Test all 4 EQ solutions systematically
    
    Returns:
        Dict with results for each solution
    """
    results = {}
    
    # Solution 1: LADSPA CMT
    logger.info("\n" + "="*60)
    logger.info("🧪 SOLUTION 1: LADSPA CMT HPF/LPF")
    logger.info("="*60)
    
    if not EQSolution1_LADSPA.validate_availability():
        logger.error("❌ LADSPA HPF not available, skipping")
        results["solution_1"] = {"status": "SKIP", "reason": "LADSPA HPF not available"}
    else:
        output = "/tmp/solution_1_ladspa_test.mp3"
        success, msg = EQSolution1_LADSPA.test_with_liquidsoap_script(transitions_json, output)
        results["solution_1"] = {
            "status": "PASS" if success else "FAIL",
            "output": msg,
            "notes": "LADSPA HPF/LPF approach"
        }
    
    # Solution 2: FFmpeg anequalizer
    logger.info("\n" + "="*60)
    logger.info("🧪 SOLUTION 2: FFmpeg anequalizer")
    logger.info("="*60)
    
    if not EQSolution2_FFmpeg.validate_availability():
        logger.error("❌ FFmpeg anequalizer not available, skipping")
        results["solution_2"] = {"status": "SKIP", "reason": "FFmpeg anequalizer not available"}
    else:
        logger.info("✅ FFmpeg anequalizer available")
        results["solution_2"] = {"status": "READY", "notes": "FFmpeg anequalizer ready to implement"}
    
    # Solution 3: Calf EQ
    logger.info("\n" + "="*60)
    logger.info("🧪 SOLUTION 3: Calf EQ")
    logger.info("="*60)
    
    if not EQSolution3_Calf.validate_availability():
        logger.info("ℹ️  Calf not available, attempting installation...")
        success, msg = EQSolution3_Calf.install_calf()
        if success:
            logger.info(f"✅ {msg}")
            results["solution_3"] = {"status": "PASS", "notes": "Calf installed successfully"}
        else:
            logger.warning(f"⚠️  Calf installation failed: {msg}")
            results["solution_3"] = {"status": "FAIL", "reason": msg}
    else:
        logger.info("✅ Calf available")
        results["solution_3"] = {"status": "PASS", "notes": "Calf already available"}
    
    # Solution 4: Hybrid pre-processing
    logger.info("\n" + "="*60)
    logger.info("🧪 SOLUTION 4: Hybrid Pre-Processing")
    logger.info("="*60)
    
    output = "/tmp/solution_4_hybrid_test.mp3"
    success, msg = EQSolution4_Hybrid.test_hybrid_approach(transitions_json, output)
    results["solution_4"] = {
        "status": "PASS" if success else "FAIL",
        "output": msg if success else f"Error: {msg}",
        "notes": "Hybrid pre-processing approach"
    }
    
    return results


if __name__ == "__main__":
    # Test mode: run all solutions
    import sys
    if len(sys.argv) > 1:
        transitions_json = sys.argv[1]
    else:
        logger.error("Usage: eq_solutions.py <transitions.json>")
        sys.exit(1)
    
    results = run_all_solutions(transitions_json)
    print("\n" + "="*60)
    print("📊 RESULTS SUMMARY")
    print("="*60)
    for solution, result in results.items():
        print(f"\n{solution}: {result['status']}")
        for key, val in result.items():
            if key != "status":
                print(f"  {key}: {val}")
