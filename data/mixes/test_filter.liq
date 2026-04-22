# Test: sequence + filter.rc only
track_0 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/01. Intro.m4a"))
track_0 = ffmpeg.raw.decode.audio(track_0)
track_0 = stretch(ratio=1.032, track_0)

track_1 = once(single("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/02. Don't Miss Your Shot.m4a"))
track_1 = ffmpeg.raw.decode.audio(track_1)
track_1 = stretch(ratio=1.016, track_1)

mixed = sequence([track_0, track_1])
mixed = filter.rc(frequency=30.0, mode="high", mixed)
mixed = clock(sync="none", mixed)
output.file(%mp3(bitrate=320), "/app/data/mixes/test_filter.mp3", fallible=true, on_stop=shutdown, mixed)
