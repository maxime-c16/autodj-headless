# AutoDJ-Headless Pro DJ Mix
# Architecture: sequence() + cross() with bass swap, filter, limiter
# DJ EQ Automation: DISABLED
# Crossfade: 15.1s (8 bars at 127 BPM)

# === DJ TRANSITION (bass swap crossfade) ===
def dj_transition(a, b) =
  # Classic DJ technique: HPF outgoing (cuts bass), LPF incoming (warm entry)
  # filter.rc() works in cross() callbacks in Liq 2.1.3 (butterworth does not)
  a_cut = filter.rc(frequency=300.0, mode="high", a.source)
  a_faded = fade.out(type="sin", duration=15.1, a_cut)
  b_warm = filter.rc(frequency=2500.0, mode="low", b.source)
  b_faded = fade.in(type="sin", duration=15.1, b_warm)
  add(normalize=false, [a_faded, b_faded])
end

# === TRACK DEFINITIONS ===
# Track 1: unknown_0
#   BPM: 124 -> 128, Stretch: 1.032
track_0 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/01. Intro.m4a"))
track_0 = ffmpeg.raw.decode.audio(track_0)
track_0 = stretch(ratio=1.032, track_0)

# Track 2: unknown_1
#   BPM: 128 -> 130, Stretch: 1.016
track_1 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/02. Don't Miss Your Shot.m4a"))
track_1 = ffmpeg.raw.decode.audio(track_1)
track_1 = stretch(ratio=1.016, track_1)

# Track 3: unknown_2
#   BPM: 130 -> 132, Stretch: 1.015
track_2 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/03. Blackout.m4a"))
track_2 = ffmpeg.raw.decode.audio(track_2)
track_2 = stretch(ratio=1.015, track_2)

# Track 4: unknown_3
#   BPM: 132 -> 128, Stretch: 0.970
track_3 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/04. Oblivion.m4a"))
track_3 = ffmpeg.raw.decode.audio(track_3)
track_3 = stretch(ratio=0.970, track_3)

# Track 5: unknown_4
#   BPM: 128 -> 126, Stretch: 0.984
track_4 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/05. Molten Core.m4a"))
track_4 = ffmpeg.raw.decode.audio(track_4)
track_4 = stretch(ratio=0.984, track_4)

# Track 6: unknown_5
#   BPM: 126 -> 124, Stretch: 0.984
track_5 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/06. Rusty Chains.m4a"))
track_5 = ffmpeg.raw.decode.audio(track_5)
track_5 = stretch(ratio=0.984, track_5)

# Track 7: unknown_6
#   BPM: 124 -> 124, Stretch: 1.000
track_6 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a"))
track_6 = ffmpeg.raw.decode.audio(track_6)


# === SEQUENTIAL PLAYBACK + CROSSFADE ===
playlist = sequence([track_0, track_1, track_2, track_3, track_4, track_5, track_6])
mixed = cross(duration=15.1, dj_transition, playlist)

# === MASTER PROCESSING ===
# Sub-bass HPF skipped: filter.rc() silences audio in Liq 2.1.3; butterworth broken in 2.2.x

# Soft limiter (prevent clipping from overlapping transitions)
# Compress with proper Liquidsoap 2.1.3 parameters (times in ms, not seconds)
mixed = compress(threshold=-20.0, attack=50.0, release=400.0, ratio=4.0, gain=0.0, mixed)

# Offline clock: run as fast as possible (no real-time sync)
mixed = clock(sync="none", mixed)

# === OUTPUT ===
output.file(%mp3(bitrate=320), "/app/data/mixes/rusty-chains-showcase-2026-02-26.mp3", fallible=true, on_stop=shutdown, mixed)
