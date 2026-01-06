"""
Set Generation Module: Create playlists and transition plans.

Per SPEC.md § 2.2:
- Greedy graph traversal (no backtracking)
- Max 30 sec total runtime
- Peak memory ≤ 512 MiB
- Output: playlist.m3u and transition_map.json
"""

__all__ = ["selector", "energy", "playlist"]
