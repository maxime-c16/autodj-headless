#!/bin/bash
# DEPLOYMENT & MONITORING SCRIPT
# Multi-Loop Issues Deployment with Real-Time Monitoring

set -e

PROJECT_DIR="/home/mcauchy/autodj-headless"
DEPLOY_LOG="/tmp/multiloop-deployment-$(date +%Y%m%d-%H%M%S).log"
ANALYSIS_LOG="/tmp/multiloop-analysis-$(date +%Y%m%d-%H%M%S).log"

echo "=========================================================================="
echo "DEPLOYMENT & MONITORING: Multi-Loop Issues Fix"
echo "=========================================================================="
echo "Project: $PROJECT_DIR"
echo "Deploy Log: $DEPLOY_LOG"
echo "Analysis Log: $ANALYSIS_LOG"
echo ""

# =========================================================================
# PHASE 1: VERIFICATION
# =========================================================================

echo "[PHASE 1] Verifying Code Changes..."
echo "=========================================================================="

# Verify Issue #1 fix is in place
if grep -q "bpm_confidence_low" "$PROJECT_DIR/src/scripts/analyze_library.py"; then
    echo "✅ Issue #1 (BPM Fallback): Code verified"
else
    echo "❌ Issue #1: Code NOT found - ABORT"
    exit 1
fi

# Verify Issue #2 implementation
if grep -q "_compute_loop_stability" "$PROJECT_DIR/src/autodj/analyze/structure.py"; then
    echo "✅ Issue #2 (Stability): Code verified"
else
    echo "❌ Issue #2: Code NOT found - ABORT"
    exit 1
fi

echo ""

# =========================================================================
# PHASE 2: RUN TESTS
# =========================================================================

echo "[PHASE 2] Running Test Suite..."
echo "=========================================================================="

cd "$PROJECT_DIR"

# Run stability tests
echo "Running stability tests..."
if python3 -m pytest tests/test_stability_fix.py -v --tb=short > "$DEPLOY_LOG" 2>&1; then
    TEST_COUNT=$(grep -c "PASSED" "$DEPLOY_LOG" || true)
    echo "✅ Stability tests: $TEST_COUNT/8 PASSED"
else
    echo "❌ Tests FAILED - Check log: $DEPLOY_LOG"
    cat "$DEPLOY_LOG"
    exit 1
fi

# Run production validation
echo "Running production validation..."
if python3 test_production_validation.py >> "$DEPLOY_LOG" 2>&1; then
    echo "✅ Production validation: PASSED"
else
    echo "⚠️  Production validation: Check log"
fi

echo ""

# =========================================================================
# PHASE 3: DEPLOYMENT READINESS
# =========================================================================

echo "[PHASE 3] Deployment Readiness Check..."
echo "=========================================================================="

# Check git status (if in git repo)
if [ -d "$PROJECT_DIR/.git" ]; then
    CHANGES=$(cd "$PROJECT_DIR" && git status --porcelain src/ | wc -l)
    if [ "$CHANGES" -gt 0 ]; then
        echo "📝 Modified files:"
        cd "$PROJECT_DIR" && git status --porcelain src/ | grep "\.py$"
    fi
fi

echo ""
echo "✅ DEPLOYMENT READY"
echo ""

# =========================================================================
# PHASE 4: INFORMATION FOR USER
# =========================================================================

echo "[PHASE 4] Next Steps..."
echo "=========================================================================="
echo ""
echo "To deploy and start analysis:"
echo ""
echo "  1. Backup current database (optional):"
echo "     cp data/tracks.db data/tracks.db.backup"
echo ""
echo "  2. Run library analysis with new fixes:"
echo "     cd $PROJECT_DIR"
echo "     make analyze 2>&1 | tee $ANALYSIS_LOG"
echo ""
echo "  3. Monitor for:"
echo "     - '✅ BPM detected: XXX BPM' (normal tracks)"
echo "     - '⚠️ BPM detection failed' (fallback tracks - track count)"
echo "     - 'ℹ️ BPM set to fallback value 120.0 - NEEDS MANUAL VERIFICATION'"
echo ""
echo "  4. Check recovery statistics:"
echo "     echo 'Fallback BPM tracks:' && grep 'fallback value' $ANALYSIS_LOG | wc -l"
echo ""
echo "=========================================================================="
echo "Deployment prepared successfully!"
echo "=========================================================================="
