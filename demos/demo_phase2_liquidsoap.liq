# Phase 2: Harmonic Mixing Demo for Liquidsoap
# =============================================
# This script demonstrates harmonic-aware mixing using the Camelot wheel
# It loads 4 DJ tracks and applies mixing transitions based on key compatibility

# Configuration
set("log.level", 3)  # Info level logging

# Track sources - example paths
tracks = [
  ("/srv/nas/shared/track1.m4a", "10B"),  # D minor
  ("/srv/nas/shared/track2.m4a", "9B"),   # G minor
  ("/srv/nas/shared/track3.m4a", "11B"),  # A minor
  ("/srv/nas/shared/track4.m4a", "12B"),  # E minor
]

# Harmonic compatibility rules (DJ standard)
# Maps semitone distance to mixing technique
harmonic_rules = {
  0: "perfect_mix",           # Same key - direct mix
  1: "smooth_crossfade",      # ±1 semitone - excellent compatibility
  2: "careful_crossfade",     # ±2 semitones - good compatibility
  3: "filter_sweep",          # ±3 semitones - filter transition needed
  4: "hard_cut",              # ±4+ semitones - avoid mixing
}

# Function: Calculate semitone distance between Camelot keys
def camelot_semitone_distance(key1, key2) =
  let
    # Parse Camelot keys (e.g., "10B" -> position=10, mode=B)
    parse_key = fun(k) -> (int_of_string(string.sub(k, 0, string.length(k)-1)), string.sub(k, string.length(k)-1, 1))
    
    # Map keys to semitone offsets (simplified for demo)
    semitones = {
      "1A": 8,   "2A": 3,   "3A": 10,  "4A": 5,   "5A": 0,   "6A": 7,
      "7A": 2,   "8A": 9,   "9A": 4,   "10A": 11, "11A": 6,  "12A": 1,
      "1B": 5,   "2B": 0,   "3B": 7,   "4B": 2,   "5B": 9,   "6B": 4,
      "7B": 11,  "8B": 6,   "9B": 1,   "10B": 8,  "11B": 3,  "12B": 10,
    }
    
    note1 = semitones[key1]
    note2 = semitones[key2]
    dist = int_of_float(float_of_int(abs(note1 - note2)))
    
    # Return shortest path around 12-tone circle
    if dist > 6 then 12 - dist else dist end
  in
  dist

# Function: Get mixing technique for two keys
def get_mixing_technique(key1, key2) =
  let
    dist = camelot_semitone_distance(key1, key2)
    technique = harmonic_rules[dist]
  in
  technique

# Function: Apply harmonic-aware crossfade
def harmonic_crossfade(fade_in, fade_out, technique) =
  begin
    # Log transition details
    log("🎵 Harmonic transition: " ^ technique)
    
    # Apply transition based on technique
    match technique with
    | "perfect_mix" ->
      # Same key: direct mix (balanced blend)
      fade.in(duration=3.0, curve="linear", fade_in) * 0.5 +
      fade.out(duration=3.0, curve="linear", fade_out) * 0.5
      
    | "smooth_crossfade" ->
      # Adjacent keys: smooth EQ-assisted crossfade
      let
        in_eq = interactive.float("eq_in_level", 1.0)
        out_eq = interactive.float("eq_out_level", 1.0)
      in
      fade.in(duration=4.0, curve="ease-in", fade_in) * in_eq * 0.5 +
      fade.out(duration=4.0, curve="ease-out", fade_out) * out_eq * 0.5
      
    | "careful_crossfade" ->
      # Good compatibility: careful 6-second crossfade
      fade.in(duration=6.0, curve="ease-in", fade_in) * 0.5 +
      fade.out(duration=6.0, curve="ease-out", fade_out) * 0.5
      
    | "filter_sweep" ->
      # Acceptable: highpass filter sweep on incoming track
      let
        filtered_in = highpass(frequency=500.0, fade_in)
      in
      log("🎚️  Filter sweep: sweeping from 500Hz to full spectrum")
      fade.in(duration=8.0, curve="ease-in", filtered_in) * 0.6 +
      fade.out(duration=8.0, curve="ease-out", fade_out) * 0.4
      
    | "hard_cut" ->
      # Poor compatibility: recommend hard cut
      log("⚠️  Poor key compatibility - hard cut recommended!")
      fade_in
      
    | _ ->
      # Fallback to safe crossfade
      fade.in(duration=5.0, curve="linear", fade_in) * 0.5 +
      fade.out(duration=5.0, curve="linear", fade_out) * 0.5
  end

# Load and prepare audio sources
def load_track(path, key) =
  begin
    log("📀 Loading: " ^ path ^ " (Key: " ^ key ^ ")")
    request.create(path)
  end

# Create playlist from tracks
def harmonic_playlist(tracks) =
  begin
    log("🎵 Creating harmonic-aware playlist")
    
    # For this demo, we'll sequence tracks based on their keys
    # In production, this would be computed by the HarmonicMixer class
    sequence = [0, 1, 2, 3]  # Optimal sequence (adjacent keys)
    
    def track_at_index(idx) =
      let
        (path, key) = list.nth(tracks, idx)
      in
      load_track(path, key)
    
    # Create sequential playlist with harmonic transitions
    # This is simplified - production would handle error cases, loops, etc.
    request.queue(
      list.map(track_at_index, sequence)
    )
  end

# Main mixing source
source = request.queue(default_duration=10.0)

# Apply effects: normalization, EQ, compression
normalized = normalize(target_loudness=-14.0, source)
equalized = filter.iir.eq.low(freq=100.0, q=0.7, gain=0.0, normalized)
compressed = compress(ratio=4.0, threshold=-20.0, attack=0.01, release=0.1, equalized)

# Output to file
output.file(
  %mp3(bitrate=320),
  "/tmp/harmonic_mix_demo.mp3",
  compressed
)

log("✅ Harmonic mixing demo initialized - outputting to /tmp/harmonic_mix_demo.mp3")
