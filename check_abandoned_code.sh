#!/bin/bash
# Abandoned Code Detection Script
# Runs before major work to find code that exists but isn't integrated

set -e

REPO="/home/mcauchy/autodj-headless"
cd "$REPO"

echo "🔍 ABANDONED CODE DETECTION"
echo "======================================"
echo ""

# Check /scripts/ for tests related to current work
echo "📋 Test scripts in /scripts/ (not in pipeline):"
echo "---"
find scripts/ -name "*.py" -type f -newer MEMORY.md 2>/dev/null | while read file; do
    size=$(wc -l < "$file")
    date=$(stat -c %y "$file" 2>/dev/null | cut -d' ' -f1)
    echo "  $file ($size lines, created $date)"
done
echo ""

# Check for Peaking EQ implementations
echo "🎛️ EQ-related code:"
echo "---"
find . -path ./venv -prune -o -name "*eq*.py" -type f -print 2>/dev/null | grep -v venv | while read f; do
    integrated=$(grep -l "$f" src/autodj/render/render.py 2>/dev/null || echo "NOT INTEGRATED")
    if [ "$integrated" = "NOT INTEGRATED" ]; then
        echo "  ⚠️  $f (NOT in render pipeline)"
    else
        echo "  ✅ $f (integrated)"
    fi
done
echo ""

# Check for drop detection
echo "🎯 Drop detection code:"
echo "---"
find . -path ./venv -prune -o -name "*drop*.py" -type f -print 2>/dev/null | grep -v venv | while read f; do
    integrated=$(grep -l "drop" src/autodj/generate/aggressive_eq_annotator.py 2>/dev/null || echo "NOT FOUND")
    if [ "$integrated" = "NOT FOUND" ]; then
        echo "  ⚠️  $f (NOT in annotator)"
    else
        echo "  ✅ $f (referenced)"
    fi
done
echo ""

echo "======================================"
echo "Review items above with ⚠️ before coding!"
