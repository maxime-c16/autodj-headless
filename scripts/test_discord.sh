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
    echo ""
    echo "   To set up Discord integration:"
    echo "   1. Follow the guide in DISCORD_SETUP.md"
    echo "   2. Get your bot token from Discord Developer Portal"
    echo "   3. Export it: export DISCORD_TOKEN='your_token_here'"
    echo ""
    echo "   Then retry this test:"
    echo "   export DISCORD_TOKEN='...' DISCORD_CHANNEL_ID='...' bash scripts/test_discord.sh"
    exit 1
fi

# Check if channel ID is set
if [[ -z "${DISCORD_CHANNEL_ID}" ]]; then
    echo "❌ DISCORD_CHANNEL_ID not set"
    echo ""
    echo "   To set up Discord integration:"
    echo "   1. Follow the guide in DISCORD_SETUP.md"
    echo "   2. Get your channel ID from Discord (right-click channel)"
    echo "   3. Export it: export DISCORD_CHANNEL_ID='your_channel_id'"
    echo ""
    echo "   Then retry this test:"
    echo "   export DISCORD_TOKEN='...' DISCORD_CHANNEL_ID='...' bash scripts/test_discord.sh"
    exit 1
fi

echo "✅ DISCORD_TOKEN is set"
echo "✅ DISCORD_CHANNEL_ID is set"
echo ""

echo "Testing Discord notifier..."
docker-compose -f docker/compose.dev.yml exec -T \
  -e DISCORD_TOKEN="${DISCORD_TOKEN}" \
  -e DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID}" \
  autodj python3 << 'PYTHON'
import sys
sys.path.insert(0, '/app/src')

from autodj.discord.notifier import DiscordNotifier
from autodj.config import Config

# Load config (will process env: references)
config = Config.load('/app/configs/autodj.toml')
notifier = DiscordNotifier(config_dict=config.data)

if not notifier.enabled:
    print("❌ Notifier is disabled - check TOKEN and CHANNEL_ID")
    sys.exit(1)

print("✅ Notifier initialized")
print("")
print("Testing notification...")
notifier.post_phase_complete('Integration Test', {
    'Message': 'Discord integration working!',
    'Time': 'Just now',
    'Status': '✅ Success'
})

print("")
print("✅ Test notification sent to Discord!")
PYTHON

echo ""
echo "======================================"
echo "Test complete!"
echo "======================================"
echo ""
echo "Check your Discord #music channel for a notification."
echo "If you see it, the integration is working correctly!"

