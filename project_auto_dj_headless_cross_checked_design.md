# Project AutoDJ‑Headless

## 1. Project Overview
**AutoDJ‑Headless** is an offline, resource‑aware automated DJ system designed for a Debian 12 home‑lab server with constrained CPU (2 cores) and RAM (~4 GiB). The project transforms a static music library (served by Navidrome) into periodically generated, DJ‑style mixed sets using algorithmic beatmatching, harmonic mixing, phrasing, looping, and EQ/filter transitions.

The design is cross‑checked against:
- The research paper *Automating the Decks: Algorithmic DJ Systems for Headless Architectures* fileciteturn0file0
- Your **actual server constraints and topology** (CPU, RAM, Docker usage, open ports, FD limits)

The system explicitly avoids real‑time audio and GUI software, favoring **offline rendering** for stability.

---

## 2. Goals and Non‑Goals
### Goals
- Produce realistic DJ‑style mixes (not simple crossfades)
- Operate fully headless and offline
- Respect tight RAM and CPU budgets
- Integrate cleanly with Navidrome
- Be deterministic, restart‑safe, and schedulable

### Non‑Goals
- Live streaming
- Real‑time performance
- GUI interaction
- ML inference during mix rendering

---

## 3. System Constraints (Cross‑Checked)
| Resource | Available | Design Budget |
|-------|-----------|---------------|
| CPU | 2 cores (Pentium 3550M) | ≤ 0.5–1 core burst |
| RAM | 3.7 GiB total | ≤ 512 MiB per job |
| Disk | ~600 GB free | Disk‑first buffering |
| FD limit | 1024 (default) | Raise to ≥ 8192 |
| Network | Busy (Docker, SMB, NFS) | Loopback‑only |

**Design implication:** analysis and rendering must be **sequential, streaming, and short‑lived**.

---

## 4. High‑Level Architecture

```
+-------------------+
|  Music Library    |
|  (Navidrome/NAS)  |
+---------+---------+
          |
          v
+-------------------+
|  MIR Analyzer     |  (Python)
|  BPM / Key / Cues |
+---------+---------+
          |
          v
+-------------------+
|  Set Generator    |  (Python)
|  Playlist + Plan  |
+---------+---------+
          |
          v
+-------------------+
|  Render Engine    |  (Liquidsoap)
|  Offline Mixdown  |
+---------+---------+
          |
          v
+-------------------+
|  Output Mix File  |
|  (served by ND)   |
+-------------------+
```

Control plane (Python) is **stateless and discrete**.  
Data plane (Liquidsoap) is **streaming and memory‑bounded**.

---

## 5. Component Design

### 5.1 MIR Analyzer (Python)
**Purpose:** Pre‑process tracks once; never analyze during rendering.

- BPM + beat grid: `aubio` (chosen over Librosa to minimize RAM)
- Key detection: `essentia-streaming` or `keyfinder-cli`
- Cue points:
  - Cue‑In (first energetic downbeat)
  - Cue‑Out (energy drop)
  - Optional loop window (16–32 beats)

**Storage:**
- Written into tags (TBPM, TKEY)
- Supplemental SQLite DB for cue/loop metadata

**Execution model:**
- One file at a time
- Hard RAM cap (Docker/systemd)

---

### 5.2 Set Generator (Python)
**Purpose:** Decide *what* to mix and *how*, without touching audio samples.

**Algorithm:**
1. Select seed track
2. Traverse library graph using constraints:
   - BPM ± 4 %
   - Camelot‑compatible key
   - Energy continuity
   - No repeats
3. Emit `playlist.m3u`
4. Emit `transition_map.json`

**Output example:**
```json
{
  "track": "song_B.mp3",
  "mix_in": "cue_in",
  "duration_bars": 16,
  "effect": "filter_swap",
  "target_bpm": 126
}
```

---

### 5.3 Render Engine (Liquidsoap)
**Purpose:** Perform DSP efficiently under tight memory constraints.

Key features used:
- Offline clock (`sync=false`)
- Streaming decode/encode
- `smart_crossfade`
- Time‑stretch (`stretch`)
- IIR filters (LPF/HPF)
- Optional LADSPA EQ

**Why Liquidsoap:**
- Proven headless reliability
- Very low RAM footprint
- Native offline rendering support

---

## 6. Resource Controls (Mandatory)

### Runtime limits
- CPU: `--cpus=0.5`
- RAM: `--memory=512m`
- Nice: `nice -n 19`
- IO: `ionice -c 3`

### OS tuning (host)
- Raise `nofile` to ≥ 8192
- Prefer loopback binding only

---

## 7. Scheduling Model

| Task | Frequency | Time |
|----|----------|------|
| MIR scan | Nightly | 02:30 |
| Set generation | Weekly | 03:00 |
| Rendering | Weekly | Immediately after |

Jobs are **short‑lived** and exit cleanly to free memory.

---

## 8. Failure & Safety Design
- Stateless jobs → safe restarts
- Partial outputs discarded
- No long‑running daemons
- Docker/systemd enforced limits
- Navidrome unaffected by failure

---

## 9. Expected Output
- 30–90 min DJ‑style mix files
- Seamless beat‑matched transitions
- Harmonic coherence
- No audible clipping or bass clash
- Zero real‑time audio dependency

---

## 10. Validation Against Research
| Research Requirement | Implemented |
|--------------------|------------|
| Headless | ✅ |
| Offline rendering | ✅ |
| Beatmatching | ✅ |
| Harmonic mixing | ✅ |
| Loops & EQ | ✅ |
| Low RAM | ✅ |
| NAS‑safe | ✅ |

Aligned with conclusions of *Automating the Decks* fileciteturn0file0

---

## 11. Next Implementation Steps
1. Create repo structure
2. Implement MIR analyzer (aubio + keyfinder)
3. Implement generator logic
4. Write Liquidsoap render script
5. Apply OS limits
6. Dry‑run with 3‑track test set

---

**Status:** Architecture is cross‑checked, resource‑bounded, and implementation‑ready.

