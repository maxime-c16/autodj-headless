# Test: just one track, no cross/filter/compress
s = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/01. Intro.m4a"))
s = ffmpeg.raw.decode.audio(s)
s = stretch(ratio=1.032, s)
s = clock(sync="none", s)
output.file(%mp3(bitrate=320), "/app/data/mixes/test_simple.mp3", fallible=true, on_stop=shutdown, s)
