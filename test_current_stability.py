#!/usr/bin/env python3
"""
Diagnostic test for current _compute_loop_stability implementation
"""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))

from autodj.analyze.structure import _compute_loop_stability

def create_identical_sine():
    sr = 44100
    loop_duration = 2.0
    loop_samples = int(sr * loop_duration)
    t = np.linspace(0, loop_duration, loop_samples)
    loop = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    return loop.copy(), loop.copy()

def create_drop_loop():
    sr = 44100
    loop_duration = 2.0
    loop_samples = int(sr * loop_duration)
    t = np.linspace(0, loop_duration, loop_samples)
    loop1 = (0.7 * np.sin(2 * np.pi * 200 * t) + 0.3 * np.sin(2 * np.pi * 2000 * t))
    loop2 = (0.65 * np.sin(2 * np.pi * 200 * t) + 0.28 * np.sin(2 * np.pi * 1900 * t))
    return loop1.astype(np.float32), loop2.astype(np.float32)

def create_different_freqs():
    sr = 44100
    loop_duration = 2.0
    loop_samples = int(sr * loop_duration)
    t = np.linspace(0, loop_duration, loop_samples)
    loop1 = 0.8 * np.sin(2 * np.pi * 100 * t)
    loop2 = 0.8 * np.sin(2 * np.pi * 5000 * t)
    return loop1.astype(np.float32), loop2.astype(np.float32)

# Test the ACTUAL function on real-world drops
print("=" * 70)
print("TESTING CURRENT _compute_loop_stability IMPLEMENTATION")
print("=" * 70)

sr = 44100
loop_duration = 2.0
loop_samples = int(sr * loop_duration)

tests = [
    ("clean sine (identical)", create_identical_sine),
    ("drop loop (similar)", create_drop_loop),
    ("different frequencies", create_different_freqs),
]

for name, generator in tests:
    first, second = generator()
    stability = _compute_loop_stability(first, second)
    print(f"{name:30s}: {stability:.4f}")

print("\nTesting with drops from real showcase mix...")
# Test with drop-like signals (like the ones from real analysis)
t = np.linspace(0, loop_duration, loop_samples)

# HIGH ENERGY DROP (what was returning 0%)
drop_section = 0.8 * np.sin(2 * np.pi * 200 * t) + 0.6 * np.sin(2 * np.pi * 2000 * t)

# Split into two loops
loop1 = drop_section[:loop_samples]
loop2 = drop_section[loop_samples:min(2*loop_samples, len(drop_section))]

if len(loop2) > 0:
    stability = _compute_loop_stability(loop1[:len(loop2)], loop2)
    print(f"{'HIGH ENERGY DROP':30s}: {stability:.4f}")

print("\n" + "=" * 70)
