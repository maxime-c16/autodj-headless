# AutoDJ-Headless

## Development & Deployment Workflow Summary

*(Mac ↔ Debian Server)*

---

## 1. System Topology (Authoritative)

### Development Machine

* **OS:** macOS
* **Role:**

  * Primary code authoring
  * Git source of truth
  * No Docker builds performed locally

### Server

* **Host:** Debian 12
* **Hostname:** `deb-serv`
* **IP:** `192.168.1.57`
* **User:** `mcauchy`
* **Roles:**

  * Runtime execution
  * Docker image storage
  * Offline audio rendering
  * Navidrome media serving

### Container Orchestration

* **Dev:** `docker compose`
* **Prod:** `docker stack deploy` (Swarm)
* **Note:** One older Wi-Fi Swarm node (`retro-deb`) exists but **must not** be relied on for builds, dev, or timing-sensitive tasks.

---

## 2. Core Workflow Philosophy

### Key Rules

1. **Code is edited on the Mac only**
2. **Docker images are rebuilt rarely**
3. **Most changes never trigger a rebuild**
4. **The server is a runtime target, not a dev editor**
5. **Makefile is the single command interface**

The workflow explicitly separates:

* **Iteration (fast)** → code changes, no rebuild
* **Infrastructure changes (slow)** → image rebuilds

---

## 3. Source Control & Code Sync

### Git is the synchronization mechanism

#### On the Mac (authoritative)

```bash
git commit -am "change description"
git push
```

#### On the server

```bash
ssh mcauchy@192.168.1.57
cd ~/autodj-headless
git pull
```

**Important:**

* No code is written directly on the server
* The server never diverges from Git

---

## 4. Repository Responsibilities (High-Level)

```
autodj-headless/
├── src/        # Python + Liquidsoap source (mutable)
├── docker/     # Dockerfiles, compose, stack (rarely changes)
├── data/       # Runtime outputs (DB, playlists, mixes)
├── configs/    # Tunable parameters
└── Makefile   # Primary control interface
```

### Conceptual separation

* **src/** → logic and behavior
* **docker/** → environment
* **Makefile** → workflow contract

---

## 5. Docker Strategy

### Base Image

* Built on the server
* Contains:

  * Python runtime
  * Liquidsoap
  * ffmpeg
  * DSP dependencies
* **Does NOT contain application source**

### Why

* Enables bind-mounting source code
* Allows instant iteration
* Prevents rebuild loops

---

## 6. Development Mode (Primary Loop)

### Start dev environment (on server)

```bash
make dev-up
```

This:

* Uses `docker compose`
* Mounts `src/`, `configs/`, and `data/` into the container
* Runs with CPU/RAM limits
* Does **not** rebuild images

---

## 7. Day-to-Day Development Workflow

### Typical iteration loop

1. **Edit code on Mac**
2. Commit changes
3. SSH into server:

   ```bash
   ssh mcauchy@192.168.1.57
   cd ~/autodj-headless
   git pull
   ```
4. Run one of:

   ```bash
   make analyze
   make generate
   make render
   ```

### Feedback speed

* Seconds, not minutes
* No image rebuild
* No Swarm redeploy

---

## 8. Makefile as the Control Plane

All operational actions are executed via `make`.

### Key commands

| Command         | Purpose                     |
| --------------- | --------------------------- |
| `make dev-up`   | Start dev container         |
| `make dev-down` | Stop dev container          |
| `make analyze`  | Run MIR analysis            |
| `make generate` | Generate DJ playlist        |
| `make render`   | Render offline mix          |
| `make rebuild`  | Rebuild Docker image (rare) |

**Rule:**

> If a task cannot be run via `make`, it is not part of the supported workflow.

---

## 9. When to Rebuild Docker Images (Critical Rule)

### Rebuild **only** when:

* Python version changes
* System dependencies change
* Liquidsoap version changes
* DSP libraries change

Command:

```bash
make rebuild
```

### Never rebuild for:

* Logic changes
* Algorithm tweaks
* Transition tuning
* Playlist rules
* Config changes

---

## 10. Production Deployment (Swarm)

### Purpose

* Long-term scheduled jobs
* Stable weekly/monthly mix generation
* Not used for development

### Deploy

```bash
docker stack deploy -c docker/stack.prod.yml autodj
```

### Production rules

* No bind mounts
* Fixed image tag
* Scheduled execution only
* No interactive usage

---

## 11. Network & Reliability Constraints

* The server (`192.168.1.57`) is on wired LAN
* The Wi-Fi Swarm node:

  * Must not build images
  * Must not host dev containers
  * May run low-priority batch jobs only

---

## 12. Operational Safety Principles

* All DJ jobs are **offline**
* All jobs are **short-lived**
* Containers exit after completion
* Memory is capped (≈512 MB)
* CPU is limited (≤0.5–1 core)
* Navidrome and file services are never blocked

---

## 13. Mental Model (For Claude Code)

> The Mac is the **brain**
> Git is the **spine**
> The Debian server is the **muscle**
> Docker is **isolation**, not workflow
> Makefile is the **language of intent**

If this model is preserved, the system remains fast, safe, and maintainable.
