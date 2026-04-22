#!/usr/bin/env liquidsoap
# Configure FFmpeg decoder for ALAC M4A support
# Priority: Higher number = higher priority (tried first)

# Set FFmpeg decoder priority to highest for M4A files
# This ensures Liquidsoap uses FFmpeg for .m4a files instead of trying built-in decoders

set("decoder.ffmpeg.priority", 10)  # Highest priority
set("decoder.aac.priority", 5)       # Lower priority
set("decoder.flac.priority", 5)      # Lower priority

# Enable FFmpeg for M4A extension
add_decoder("ffmpeg-m4a",
  description="FFmpeg ALAC decoder for M4A files",
  mimes=["audio/mp4", "audio/x-m4a"],
  file_extensions=["m4a"],
  priority=10,  # Highest priority for M4A
  test=fun(file) -> begin
    if string.match(pattern=".*\\.m4a$", file) then
      1  # Can decode
    else
      0  # Cannot decode
    end
  end,
  handler=fun(file) -> begin
    # Use ffmpeg protocol to decode
    request.create("ffmpeg:#{file}")
  end
)

print("✅ FFmpeg decoder configured for M4A (ALAC) support")
