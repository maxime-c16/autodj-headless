.PHONY: help dev-up dev-down rebuild analyze generate render clean logs

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
	docker-compose -f $(DEV_COMPOSE) exec -T autodj \
		python -m src.scripts.analyze_library
	@echo "✅ Analysis complete."

generate:
	@echo "🎵 Generating DJ playlist & transition plan..."
	@echo "📊 Per SPEC.md: ≤30 sec total, ≤512 MiB RAM"
	docker-compose -f $(DEV_COMPOSE) exec -T autodj \
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

# ==================== INTERNAL TARGETS (not for direct use) ====================

.PHONY: _check-container-running
_check-container-running:
	@if ! docker-compose -f $(DEV_COMPOSE) ps | grep -q running; then \
		echo "❌ Dev container not running. Run 'make dev-up' first."; \
		exit 1; \
	fi

# Default target
.DEFAULT_GOAL := help
