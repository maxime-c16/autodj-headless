# 1. Design principles (before files)

These are the **rules the repo enforces**, not just suggestions.

### Rule 1 — *Images are infrastructure, code is mutable*

* Docker images change **rarely**
* Source code changes **constantly**
* Therefore: **code is never baked into images in dev**

### Rule 2 — *Every action must be runnable with `make`*

* No memorizing long commands
* No tribal knowledge
* `make` becomes your interface contract

### Rule 3 — *One responsibility per layer*

* Python → decision making
* Liquidsoap → DSP
* Makefile → orchestration
* Docker → isolation, not logic

### Rule 4 — *Fast feedback beats elegance*

* 5-second loop > “perfect” architecture
* Offline DJ allows us to restart aggressively

---

# 2. Repository layout (authoritative)

```
autodj-headless/
│
├── Makefile
├── README.md
├── .env
├── .gitignore
│
├── docker/
│   ├── Dockerfile.base
│   ├── compose.dev.yml
│   └── stack.prod.yml
│
├── src/
│   ├── autodj/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── analyze/
│   │   │   ├── bpm.py
│   │   │   ├── key.py
│   │   │   └── cues.py
│   │   │
│   │   ├── generate/
│   │   │   ├── selector.py
│   │   │   ├── energy.py
│   │   │   └── playlist.py
│   │   │
│   │   ├── render/
│   │   │   ├── render.liq
│   │   │   └── transitions.liq
│   │   │
│   │   └── cli.py
│   │
│   └── scripts/
│       ├── analyze_library.py
│       ├── generate_set.py
│       └── render_set.py
│
├── data/
│   ├── db/
│   │   └── metadata.sqlite
│   ├── playlists/
│   └── mixes/
│
├── configs/
│   ├── autodj.toml
│   └── liquidsoap.conf
│
└── docs/
    ├── architecture.md
    └── workflow.md
```

Now let’s **explain why this works**.

---

# 3. Why this layout is shaped this way

## 3.1 `docker/` — infrastructure only

```
docker/
├── Dockerfile.base
├── compose.dev.yml
└── stack.prod.yml
```

### Why

* Docker files are **not app logic**
* They change rarely
* Keeping them isolated avoids accidental coupling

### `Dockerfile.base`

* Installs:

  * Python
  * Liquidsoap
  * ffmpeg
  * aubio / keyfinder / ladspa
* **Does NOT copy `src/`**

This is what allows instant reloads.

---

## 3.2 `src/autodj/` — the brain

This is **your domain logic**.

```
autodj/
├── analyze/
├── generate/
├── render/
└── cli.py
```

### Why this separation matters

| Folder   | Responsibility           |
| -------- | ------------------------ |
| analyze  | MIR: BPM, key, structure |
| generate | playlist + transitions   |
| render   | Liquidsoap glue          |
| cli.py   | one entrypoint           |

This mirrors **how a human DJ thinks**:

1. Know the tracks
2. Choose the next track
3. Decide *how* to mix it
4. Execute

---

## 3.3 `scripts/` — thin executable layer

Example:

```python
# generate_set.py
from autodj.generate.playlist import generate
generate()
```

### Why

* Keeps business logic importable & testable
* Scripts are **replaceable**
* Makes Makefile simple

---

## 3.4 `data/` — runtime artifacts (never committed)

```
data/
├── db/
├── playlists/
└── mixes/
```

### Why

* These are **outputs**, not code
* They change constantly
* Keeping them local avoids Git pollution

This also maps cleanly to Docker volumes.

---

## 3.5 `configs/` — human-tuned parameters

Example:

```toml
[mix]
target_duration_minutes = 60
bpm_tolerance = 0.04

[resources]
max_ram_mb = 512
```

### Why

* No magic numbers in code
* Easy to tune without redeploy
* Makes experimentation safe

---

# 4. The Makefile (your new control plane)

This is the most important part.

## 4.1 Makefile goals

* **Declarative**
* **Idempotent**
* **Readable**

---

## 4.2 Example Makefile (annotated)

```makefile
PROJECT=autodj
DEV_COMPOSE=docker/compose.dev.yml

.PHONY: help
help:
	@echo "AutoDJ commands:"
	@echo "  make dev-up        Start dev container"
	@echo "  make dev-down      Stop dev container"
	@echo "  make analyze       Analyze music library"
	@echo "  make generate      Generate playlist"
	@echo "  make render        Render mix"
	@echo "  make rebuild       Rebuild base image"
```

### Why

* Self-documenting
* No README hunting

---

### Dev lifecycle

```makefile
dev-up:
	docker compose -f $(DEV_COMPOSE) up -d

dev-down:
	docker compose -f $(DEV_COMPOSE) down
```

**Why**

* Dev = Compose, not Swarm
* Faster
* Cleaner logs

---

### Analysis

```makefile
analyze:
	docker compose -f $(DEV_COMPOSE) exec autodj \
		python scripts/analyze_library.py
```

**Why**

* Runs *inside* the container
* Uses mounted source
* Zero rebuild

---

### Generation

```makefile
generate:
	docker compose -f $(DEV_COMPOSE) exec autodj \
		python scripts/generate_set.py
```

---

### Rendering

```makefile
render:
	docker compose -f $(DEV_COMPOSE) exec autodj \
		python scripts/render_set.py
```

**Why**

* Liquidsoap runs isolated
* CPU/RAM limits apply
* Host stays safe

---

### Rebuild (rare)

```makefile
rebuild:
	docker build -f docker/Dockerfile.base -t autodj-base .
```

**Rule**

> If you run `make rebuild` often, something is wrong.

---

# 5. Why Makefile > shell scripts here

| Reason           | Explanation      |
| ---------------- | ---------------- |
| Explicit targets | You see intent   |
| Dependency model | Extendable later |
| Tab completion   | Muscle memory    |
| One interface    | Dev ≈ Prod       |

Make becomes your **contract with future-you**.

---

# 6. How this improves your workflow immediately

### Before

* SSH
* Edit on server
* Rebuild
* Redeploy
* Wait

### After

* Edit on Mac
* `git commit`
* `git pull`
* `make generate`
* `make render`

⏱️ **Seconds, not minutes**

---

# 7. Mental model you should keep

> Docker isolates *where* code runs
> Make decides *what* happens
> Python decides *why*
> Liquidsoap decides *how audio sounds*
