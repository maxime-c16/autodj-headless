.PHONY: help dev-up dev-down rebuild analyze generate render clean logs nightly nightly-status quick-mix quick-list quick-search

# Project Configuration
PROJECT_NAME := autodj
DEV_COMPOSE := docker/compose.dev.yml
BASE_IMAGE := autodj-base:v1.0
REGISTRY_PREFIX :=

# Docker resource limits (enforced per SPEC.md)
CPU_LIMIT := 0.5
MEMORY_LIMIT := 512m

# Help target
help:
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║           AutoDJ-Headless — Development Commands           ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "  🚀 DEVELOPMENT LIFECYCLE"
	@echo "    make dev-up           Start dev container with bind-mounts"
	@echo "    make dev-down         Stop dev container"
	@echo ""
	@echo "  🔍 MAIN WORKFLOW"
	@echo "    make analyze          Run MIR analysis on library"
	@echo "    make generate         Generate DJ playlist & transition plan"
	@echo "    make render           Render offline mix via Liquidsoap"
	@echo ""
	@echo "  🔧 INFRASTRUCTURE"
	@echo "    make rebuild          Rebuild base Docker image (rare)"
	@echo ""
	@echo "  🌙 NIGHTLY PIPELINE"
	@echo "    make nightly          Run nightly pipeline (analyze+generate+render)"
	@echo "    make nightly-status   Show last run log and output files"
	@echo ""
	@echo "  🎧 QUICK MIX (test render)"
	@echo "    make quick-mix SEED='Deine Angst' TRACK_COUNT=3"
	@echo "    make quick-mix TRACKS='track1, track2, track3'"
	@echo "    make quick-search Q='klangkuenstler'"
	@echo "    make quick-list           List all tracks in library"
	@echo ""
	@echo "  🧹 UTILITIES"
	@echo "    make clean            Remove containers & volumes"
	@echo "    make logs             Tail dev container logs"
	@echo ""
	@echo "  📖 DOCUMENTATION"
	@echo "    make help             Show this help message"
	@echo ""
	@echo "  🔗 RESOURCE LIMITS (per SPEC.md)"
	@echo "    CPU:   $(CPU_LIMIT) cores"
	@echo "    RAM:   $(MEMORY_LIMIT)"
	@echo ""
	@echo "  ⚡ WORKFLOW RULES"
	@echo "    1. Never run multiple jobs simultaneously"
	@echo "    2. Always use 'make' — never call docker-compose directly"
	@echo "    3. Rebuild only when dependencies change, not code"
	@echo ""

# ==================== DEVELOPMENT LIFECYCLE ====================

dev-up:
	@echo "📦 Starting dev container..."
	docker-compose -f $(DEV_COMPOSE) up -d
	@echo "✅ Dev container running. Use 'make logs' to view output."
	@echo ""
	@docker-compose -f $(DEV_COMPOSE) ps

dev-down:
	@echo "🛑 Stopping dev container..."
	docker-compose -f $(DEV_COMPOSE) down
	@echo "✅ Dev container stopped."

rebuild:
	@echo "🔨 Rebuilding base image: $(BASE_IMAGE)"
	@echo "⚠️  This should only run when dependencies change."
	docker build \
		--tag $(BASE_IMAGE) \
		--file docker/Dockerfile.base \
		--build-arg DEBIAN_FRONTEND=noninteractive \
		.
	@echo "✅ Image rebuild complete: $(BASE_IMAGE)"

# ==================== MAIN WORKFLOW ====================

analyze:
	@echo "🔍 Running MIR analysis..."
	@echo "📊 Per SPEC.md: Single file at a time, ≤30 sec per track, ≤512 MiB RAM"
	docker-compose -f $(DEV_COMPOSE) exec -T -e MUSIC_LIBRARY_PATH="$(MUSIC_LIBRARY_PATH)" autodj \
		python -m src.scripts.analyze_library
	@echo "✅ Analysis complete."

generate:
	@echo "🎵 Generating DJ playlist & transition plan..."
	@echo "📊 Per SPEC.md: ≤30 sec total, ≤512 MiB RAM"
	@echo ""
	@echo "💡 Tip: You can specify a seed track with:"
	@echo "   SEED_TRACK_PATH=/path/to/track.mp3 make generate"
	@echo "   SEED_TRACK_ID=track_id_hex make generate"
	@echo ""
	docker-compose -f $(DEV_COMPOSE) exec -T -e SEED_TRACK_PATH="$(SEED_TRACK_PATH)" -e SEED_TRACK_ID="$(SEED_TRACK_ID)" autodj \
		python -m src.scripts.generate_set
	@echo "✅ Playlist & transitions generated."

render:
	@echo "🎚️  Rendering offline mix..."
	@echo "📊 Per SPEC.md: ≤7 min for 60-min mix, ≤512 MiB RAM"
	docker-compose -f $(DEV_COMPOSE) exec -T autodj \
		python -m src.scripts.render_set
	@echo "✅ Mix rendering complete. Check data/mixes/ for output."

# ==================== UTILITIES ====================

clean:
	@echo "🧹 Cleaning containers & volumes..."
	docker-compose -f $(DEV_COMPOSE) down -v
	@echo "✅ Cleanup complete."

logs:
	@echo "📜 Tailing dev container logs (Ctrl+C to exit)..."
	docker-compose -f $(DEV_COMPOSE) logs -f --tail=50

# ==================== VALIDATION ====================

validate-config:
	@echo "🔐 Validating configuration..."
	docker-compose -f $(DEV_COMPOSE) exec -T autodj \
		python -c "from src.autodj.config import Config; c = Config.load(); print('✅ Config valid')"

# ==================== NIGHTLY PIPELINE ====================

nightly:
	@echo "🌙 Running nightly AutoDJ pipeline..."
	@bash $(CURDIR)/scripts/autodj-nightly.sh

nightly-status:
	@echo "🌙 Nightly Pipeline Status"
	@echo "════════════════════════════════════════"
	@echo ""
	@echo "📋 Latest log:"
	@if ls $(CURDIR)/data/logs/nightly-*.log 1>/dev/null 2>&1; then \
		LATEST_LOG=$$(ls -t $(CURDIR)/data/logs/nightly-*.log | head -1); \
		echo "   $$LATEST_LOG"; \
		echo ""; \
		tail -20 "$$LATEST_LOG"; \
	else \
		echo "   No nightly logs found."; \
	fi
	@echo ""
	@echo "📦 Output mixes in /srv/nas/shared/automix/:"
	@ls -lh /srv/nas/shared/automix/autodj-mix-*.mp3 2>/dev/null || echo "   No mixes delivered yet."
	@echo ""
	@echo "💾 Local mixes in data/mixes/:"
	@ls -lh $(CURDIR)/data/mixes/*.mp3 2>/dev/null || echo "   No local mixes."

# ==================== QUICK MIX (test render) ====================

quick-mix:
	@if [ -z "$(TRACKS)" ] && [ -z "$(SEED)" ] && [ -z "$(SEED_TRACK_ID)" ]; then \
		echo "🎧 Quick Mix — test render with human-readable track names"; \
		echo ""; \
		echo "Usage:"; \
		echo "  make quick-mix SEED='Deine Angst' TRACK_COUNT=3"; \
		echo "  make quick-mix SEED='klangkuenstler' TRACK_COUNT=5"; \
		echo "  make quick-mix TRACKS='Deine Angst, Toter Schmetterling, Blood On My Hands'"; \
		echo ""; \
		echo "Browse library:"; \
		echo "  make quick-search Q='klangkuenstler'"; \
		echo "  make quick-list"; \
		exit 1; \
	fi
	@docker-compose -f $(DEV_COMPOSE) exec -T \
		-e TRACKS="$(TRACKS)" \
		-e SEED="$(SEED)" \
		-e SEED_TRACK_ID="$(SEED_TRACK_ID)" \
		-e TRACK_COUNT="$(TRACK_COUNT)" \
		autodj python3 /app/scripts/quick_mix.py

quick-list:
	@docker-compose -f $(DEV_COMPOSE) exec -T autodj \
		python3 /app/scripts/quick_mix.py --list

quick-search:
	@docker-compose -f $(DEV_COMPOSE) exec -T autodj \
		python3 /app/scripts/quick_mix.py --search "$(Q)"

# ==================== INTERNAL TARGETS (not for direct use) ====================

.PHONY: _check-container-running
_check-container-running:
	@if ! docker-compose -f $(DEV_COMPOSE) ps | grep -q running; then \
		echo "❌ Dev container not running. Run 'make dev-up' first."; \
		exit 1; \
	fi

# Default target
.DEFAULT_GOAL := help
