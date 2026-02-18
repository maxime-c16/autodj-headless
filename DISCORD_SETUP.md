# Discord Integration Setup Guide

## Overview
AutoDJ can post notifications to Discord when:
- A mix is generated
- A phase completes
- The pipeline finishes successfully
- An error occurs

## How It Works
The notifier uses Discord's REST API v10 (no `discord.py` library needed) to post embeds directly to your Discord channel.

## Setup Instructions

### Step 1: Create a Discord Bot
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Give it a name (e.g., "AutoDJ")
4. Go to "Bot" in the left sidebar
5. Click "Add Bot"
6. Under "TOKEN", click "Copy" to copy your bot token
   - ⚠️ **Keep this secret!** Treat it like a password.
   - Save it temporarily: `DISCORD_TOKEN='your_bot_token_here'`

### Step 2: Set Bot Permissions
1. Go to "OAuth2" → "URL Generator" in the developer portal
2. Select scopes: `bot`
3. Select permissions: `Send Messages`, `Embed Links`
4. Copy the generated URL and open it in your browser
5. Select your Discord server and authorize the bot

### Step 3: Get Your Channel ID
1. In Discord, enable Developer Mode
   - User Settings → Advanced → Developer Mode
2. Right-click the channel where you want notifications
3. Click "Copy Channel ID"
   - Save it temporarily: `DISCORD_CHANNEL_ID='123456789'`

### Step 4: Configure AutoDJ

#### Option A: Environment Variables (Recommended for Docker)
```bash
# Before running any AutoDJ commands:
export DISCORD_TOKEN='your_bot_token_here'
export DISCORD_CHANNEL_ID='your_channel_id_here'

# Then run:
docker-compose -f docker/compose.dev.yml exec -e DISCORD_TOKEN="$DISCORD_TOKEN" -e DISCORD_CHANNEL_ID="$DISCORD_CHANNEL_ID" autodj python3 /app/scripts/quick_mix.py --list
```

Or in Makefile (set before running):
```bash
export DISCORD_TOKEN='your_token'
export DISCORD_CHANNEL_ID='your_channel_id'
make quick-mix SEED='Deine Angst' TRACK_COUNT=3
```

#### Option B: .env File (Convenience)
Create a `.env` file in the project root:
```bash
DISCORD_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here
```

Then source it:
```bash
source .env
docker-compose -f docker/compose.dev.yml exec -e DISCORD_TOKEN -e DISCORD_CHANNEL_ID autodj python3 ...
```

#### Option C: Config File (Persistent)
Already supported in `configs/autodj.toml`:
```toml
[discord]
enabled = true
token = "env:DISCORD_TOKEN"        # Reads from environment variable
channel_id = "env:DISCORD_CHANNEL_ID"
```

If you want to hardcode (not recommended):
```toml
[discord]
enabled = true
token = "your_actual_token_here"
channel_id = "your_channel_id_here"
```

## Testing Discord Integration

### Quick Test Script
```bash
# Make the bot token and channel ID available
export DISCORD_TOKEN='your_token'
export DISCORD_CHANNEL_ID='your_channel_id'

# Run the test
bash scripts/test_discord.sh
```

Or manually:
```bash
docker-compose -f docker/compose.dev.yml exec \
  -e DISCORD_TOKEN='your_token' \
  -e DISCORD_CHANNEL_ID='your_channel_id' \
  autodj python3 << 'PYTHON'
import sys
sys.path.insert(0, '/app/src')
from autodj.discord.notifier import DiscordNotifier
notifier = DiscordNotifier()
if notifier.enabled:
    notifier.post_phase_complete('Test', {
        'Message': 'Discord integration working!',
        'Status': '✅ Success'
    })
    print("✅ Test message posted!")
else:
    print("❌ Notifier is disabled. Check TOKEN and CHANNEL_ID")
PYTHON
```

## Troubleshooting

### "Notifier disabled (missing TOKEN or CHANNEL_ID)"
**Cause:** Environment variables are not set.

**Fix:**
```bash
# Check if variables are set:
echo $DISCORD_TOKEN
echo $DISCORD_CHANNEL_ID

# If empty, export them:
export DISCORD_TOKEN='your_token'
export DISCORD_CHANNEL_ID='your_channel_id'

# Verify:
docker-compose -f docker/compose.dev.yml exec -T autodj env | grep DISCORD
```

### "Failed (403): 50001 Missing Access"
**Cause:** Bot doesn't have permission to post in the channel.

**Fix:**
1. Go to Discord Server Settings → Roles
2. Find your AutoDJ bot role
3. Enable "Send Messages" and "Embed Links" permissions
4. Or set permissions on the specific channel for the bot role

### "Failed (401): 401 Unauthorized"
**Cause:** Invalid bot token.

**Fix:**
- Verify the token is copied correctly from the Developer Portal
- Make sure there are no extra spaces or quotes
- Regenerate the token if needed (old one will stop working)

### Message not appearing?
**Checklist:**
- [ ] Token is correct (from Developer Portal → Bot → TOKEN)
- [ ] Channel ID is correct (right-click channel in Discord → Copy Channel ID)
- [ ] Bot has "Send Messages" permission in the channel
- [ ] Bot is in the Discord server
- [ ] Environment variables are passed to the container:
  ```bash
  docker-compose exec -e DISCORD_TOKEN -e DISCORD_CHANNEL_ID autodj ...
  ```

## API Reference

### DiscordNotifier Class

```python
from autodj.discord.notifier import DiscordNotifier
from autodj.config import Config

# Initialize with config (reads from env vars or config file)
config = Config.load()
notifier = DiscordNotifier(config_dict=config.data)

# Post messages
notifier.post_playlist(transitions_dict, db_path='/app/data/db/metadata.sqlite')
notifier.post_complete({'Duration': '45 min', 'Size': '150 MB'})
notifier.post_error('Rendering', 'Liquidsoap crashed')
notifier.post_phase_complete('Analysis', {'Tracks': '500'})
```

## How It Works

1. **Config Loading:** When AutoDJ starts, it loads `configs/autodj.toml`
2. **Env Substitution:** Config values like `"env:DISCORD_TOKEN"` are replaced with environment variables
3. **Initialization:** DiscordNotifier checks for token + channel_id
4. **REST API:** When enabled, it POSTs embeds to Discord's REST API v10
5. **No Blocking:** Notifications don't block the pipeline—failures are logged but don't crash

## Security Notes

- **Never commit tokens** to git. Use `.env` (in `.gitignore`) or environment variables
- **Rotate tokens** if they're ever exposed
- **Limit bot permissions** to only "Send Messages" and "Embed Links"
- **Channel-specific permissions** are fine—the bot doesn't need server-wide access

## More Information

- [Discord Developer Docs](https://discord.com/developers/docs)
- [Discord REST API v10](https://discord.com/developers/docs/reference)
- [Creating Applications](https://discord.com/developers/docs/applications/general)
