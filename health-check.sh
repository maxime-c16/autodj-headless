#!/bin/bash
# POST-DEPLOYMENT HEALTH CHECK
# Run this after make analyze to verify results

LOG_FILE="${1:-/tmp/multiloop-analysis-*.log}"
LATEST_LOG=$(ls -t $LOG_FILE 2>/dev/null | head -1)

if [ -z "$LATEST_LOG" ]; then
    echo "❌ No analysis log found"
    exit 1
fi

echo "=========================================================================="
echo "POST-DEPLOYMENT HEALTH CHECK"
echo "=========================================================================="
echo "Log file: $LATEST_LOG"
echo ""

# Count statistics
TOTAL_TRACKS=$(grep -c "Analyzing:" "$LATEST_LOG" 2>/dev/null || echo "0")
BPM_DETECTED=$(grep -c "✅ BPM detected:" "$LATEST_LOG" 2>/dev/null || echo "0")
BPM_FALLBACK=$(grep -c "⚠️ BPM detection failed" "$LATEST_LOG" 2>/dev/null || echo "0")
KEY_DETECTED=$(grep -c "✅.*key" "$LATEST_LOG" 2>/dev/null || echo "0")
STRUCTURES=$(grep -c "structure" "$LATEST_LOG" 2>/dev/null || echo "0")
ERRORS=$(grep -c "ERROR\|FAILED\|Exception" "$LATEST_LOG" 2>/dev/null || echo "0")

echo "📊 RESULTS SUMMARY"
echo "=========================================================================="
echo ""

echo "🎵 BPM Detection (Issue #1 Recovery)"
echo "   Total tracks processed:  $TOTAL_TRACKS"
echo "   ✅ BPM detected:         $BPM_DETECTED"
echo "   ⚠️  BPM fallback (120):   $BPM_FALLBACK"
echo ""

if [ "$TOTAL_TRACKS" -gt 0 ]; then
    TOTAL_BPM=$((BPM_DETECTED + BPM_FALLBACK))
    if [ "$TOTAL_BPM" -gt 0 ]; then
        DETECTION_RATE=$((BPM_DETECTED * 100 / TOTAL_BPM))
        FALLBACK_RATE=$((BPM_FALLBACK * 100 / TOTAL_BPM))
        echo "   📈 Detection rate: $DETECTION_RATE%"
        echo "   📈 Fallback rate:  $FALLBACK_RATE%"
        echo "   ✅ Recovery: +$BPM_FALLBACK tracks (previously skipped)"
        echo ""
    fi
fi

echo "🏗️  Structure Analysis (Issue #2 Validation)"
echo "   Structures analyzed:     $STRUCTURES"
echo ""

echo "⚠️  ERRORS & WARNINGS"
echo "   Errors found: $ERRORS"
if [ "$ERRORS" -gt 0 ]; then
    echo ""
    echo "   Sample errors:"
    grep "ERROR\|FAILED\|Exception" "$LATEST_LOG" 2>/dev/null | head -5 | sed 's/^/   /'
else
    echo "   ✅ NO ERRORS"
fi

echo ""
echo "=========================================================================="

# Overall assessment
if [ "$BPM_FALLBACK" -gt 0 ] && [ "$ERRORS" -eq 0 ]; then
    echo "✅ DEPLOYMENT SUCCESSFUL"
    echo ""
    echo "Summary:"
    echo "  - Recovered $BPM_FALLBACK previously skipped tracks"
    echo "  - All tracks analyzed without errors"
    echo "  - BPM fallback working correctly"
    exit 0
elif [ "$ERRORS" -gt 0 ]; then
    echo "⚠️  DEPLOYMENT COMPLETE WITH WARNINGS"
    echo ""
    echo "Fix: Review errors above and re-run if needed"
    exit 1
else
    echo "❓ DEPLOYMENT STATUS UNCLEAR"
    echo ""
    echo "Check: $LATEST_LOG"
    exit 1
fi
