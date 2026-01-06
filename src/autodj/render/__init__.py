"""
Render Engine Module: Offline DSP mixing via Liquidsoap.

Per SPEC.md § 2.3:
- Offline clock (sync=false)
- Streaming decode/encode
- smart_crossfade, time-stretch, IIR filters, optional LADSPA
- Max 7 min for 60-min mix
- Peak memory ≤ 512 MiB
"""

__all__ = ["render", "transitions"]
