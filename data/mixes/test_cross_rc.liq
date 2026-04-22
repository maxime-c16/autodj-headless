# Test: filter.rc inside cross() callback for real DJ bass swap
def dj_transition(a, b) =
  # Classic DJ technique: cut bass from outgoing, warm start for incoming
  a_cut = filter.rc(frequency=300.0, mode="high", a.source)
  a_faded = fade.out(type="sin", duration=10.0, a_cut)
  b_warm = filter.rc(frequency=2500.0, mode="low", b.source)
  b_faded = fade.in(type="sin", duration=10.0, b_warm)
  add(normalize=false, [a_faded, b_faded])
end

track_0 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/01. Intro.m4a"))
track_0 = ffmpeg.raw.decode.audio(track_0)
track_0 = stretch(ratio=1.032, track_0)

track_1 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/02. Don't Miss Your Shot.m4a"))
track_1 = ffmpeg.raw.decode.audio(track_1)
track_1 = stretch(ratio=1.016, track_1)

playlist = sequence([track_0, track_1])
mixed = cross(duration=10.0, dj_transition, playlist)
mixed = compress(threshold=-20.0, attack=50.0, release=400.0, ratio=4.0, gain=0.0, mixed)
mixed = clock(sync="none", mixed)
output.file(%mp3(bitrate=320), "/app/data/mixes/test_cross_rc.mp3", fallible=true, on_stop=shutdown, mixed)
