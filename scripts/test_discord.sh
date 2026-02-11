#!/bin/bash
# Test AutoDJ Discord Integration
# Run this to verify the notifier is working

set -e

PROJECT_DIR="/home/mcauchy/autodj-headless"
cd "$PROJECT_DIR"

echo "======================================"
echo "AutoDJ Discord Integration Test"
echo "======================================"
echo ""

# Check if token is set
if [[ -z "${DISCORD_TOKEN}" ]]; then
    echo "❌ DISCORD_TOKEN not set"
    echo "   Run: export DISCORD_TOKEN='your_token_here'"
    exit 1
fi

# Check if channel ID is set
if [[ -z "${DISCORD_CHANNEL_ID}" ]]; then
    echo "❌ DISCORD_CHANNEL_ID not set"
    echo "   Run: export DISCORD_CHANNEL_ID='your_channel_id_here'"
    exit 1
fi

echo "✅ DISCORD_TOKEN is set"
echo "✅ DISCORD_CHANNEL_ID is set"
echo ""

echo "Testing Discord notifier..."
python3 << 'PYTHON'
import sys
import os
sys.path.insert(0, '/home/mcauchy/autodj-headless')

from src.autodj.discord.notifier import DiscordNotifier

notifier = DiscordNotifier()

if not notifier.enabled:
    print("❌ Notifier is disabled - check TOKEN and CHANNEL_ID")
    sys.exit(1)

print("✅ Notifier initialized")
print("")
print("Testing phase notification...")
notifier.post_phase_complete('Test', {
    'Message': 'Integration test successful',
    'Time': 'Just now',
    'Status': '✅ Working'
})

print("✅ Notification sent to Discord!")
print("")
print("If you see this message in your Discord #music-goinfre channel,")
print("the integration is working correctly!")
PYTHON

echo ""
echo "======================================"
echo "Test complete!"
echo "======================================"
