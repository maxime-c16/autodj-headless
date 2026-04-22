#!/bin/bash
# Quick restart script for when Docker build completes

set -e

echo "🔄 Restarting autodj-dev container with new Liquidsoap 2.2.4..."
docker restart autodj-dev
sleep 5

echo "✅ Container restarted!"

cd /home/mcauchy/autodj-headless

echo "🚀 Starting nightly job with full EQ support..."
bash scripts/autodj-nightly.sh

echo "📊 Job complete! Check /srv/nas/shared/automix/ for the final mix"
