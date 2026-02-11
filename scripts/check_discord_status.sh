#!/bin/bash
# AutoDJ Discord Integration - Deployment Status
# Run this to verify everything is configured

echo "======================================"
echo "AutoDJ Discord Integration Status"
echo "======================================"
echo ""

# Check .env file
if grep -q "DISCORD_CHANNEL_ID=1462201797333749790" /home/mcauchy/apple-ripper/.env; then
    echo "✅ Discord Channel ID configured"
    echo "   Channel: #music-goinfre (1462201797333749790)"
else
    echo "❌ Discord Channel ID not found"
    exit 1
fi

# Check token
if grep -q "DISCORD_TOKEN=" /home/mcauchy/apple-ripper/.env; then
    echo "✅ Discord Bot Token configured"
else
    echo "❌ Discord Bot Token not found"
    exit 1
fi

# Check notifier module
if [ -f /home/mcauchy/autodj-headless/src/autodj/discord/notifier.py ]; then
    echo "✅ Discord Notifier module created"
    LINES=$(wc -l < /home/mcauchy/autodj-headless/src/autodj/discord/notifier.py)
    echo "   Size: $LINES lines"
else
    echo "❌ Discord Notifier module not found"
    exit 1
fi

# Check nightly script hooks
if grep -q "post_phase_complete" /home/mcauchy/autodj-headless/scripts/autodj-nightly.sh; then
    echo "✅ Nightly script integration hooks installed"
    HOOKS=$(grep -c "post_phase_complete\|post_playlist\|post_error\|post_complete" /home/mcauchy/autodj-headless/scripts/autodj-nightly.sh)
    echo "   Notification points: $HOOKS"
else
    echo "❌ Nightly script hooks not found"
    exit 1
fi

# Check requirements.txt
if grep -q "discord.py" /home/mcauchy/autodj-headless/requirements.txt; then
    echo "✅ discord.py dependency added to requirements.txt"
else
    echo "❌ discord.py not in requirements.txt"
    exit 1
fi

# Check toml config
if grep -q "\[discord\]" /home/mcauchy/autodj-headless/configs/autodj.toml; then
    echo "✅ Discord configuration section in autodj.toml"
else
    echo "❌ Discord config section not found"
    exit 1
fi

echo ""
echo "======================================"
echo "✅ DEPLOYMENT COMPLETE & READY"
echo "======================================"
echo ""
echo "📍 Nightly Run: 02:30 UTC (automatic)"
echo "📍 Manual Test: python3 scripts/quick_mix.py"
echo "📍 Quick Test: bash scripts/test_discord.sh"
echo ""
echo "All messages post to: #music-goinfre"
echo "Next run will notify Discord automatically! 🎵"
echo ""
