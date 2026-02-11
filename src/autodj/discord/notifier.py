"""
AutoDJ Discord Notifier - Posts pipeline status to Discord

Usage:
    from src.autodj.discord.notifier import DiscordNotifier
    
    notifier = DiscordNotifier()
    notifier.post_phase_complete('Analyze', {'Tracks': '697', 'Duration': '3 min'})
"""

import discord
import os
import asyncio
import threading
from datetime import datetime
from typing import Dict, Any, Optional


class DiscordNotifier:
    """Posts AutoDJ pipeline status and playlists to Discord"""
    
    def __init__(self):
        """Initialize notifier with token and channel from environment"""
        self.token = os.getenv('DISCORD_TOKEN')
        self.channel_id = os.getenv('DISCORD_CHANNEL_ID')
        self.enabled = bool(self.token and self.channel_id)
        
        if not self.enabled:
            print("[Discord] ⚠️  Notifier disabled (missing TOKEN or CHANNEL_ID)")
    
    def _send_embed_sync(self, embed: discord.Embed) -> bool:
        """Send embed to Discord (synchronous wrapper)
        
        Runs async code in a new thread with its own event loop
        """
        if not self.enabled:
            return False
        
        def run_async():
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the async function
                result = loop.run_until_complete(self._send_embed_async(embed))
                loop.close()
                return result
            except Exception as e:
                print(f"[Discord] Error in async send: {e}")
                return False
        
        # Run in thread to avoid blocking
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        thread.join(timeout=10)  # Wait max 10 seconds
        return True
    
    async def _send_embed_async(self, embed: discord.Embed) -> bool:
        """Internal async: Send embed to Discord channel
        
        Returns:
            True if successful, False otherwise
        """
        try:
            print(f"[Discord] 📤 Sending message to channel {self.channel_id}...")
            
            # Create client with proper intents
            intents = discord.Intents.default()
            client = discord.Client(intents=intents)
            
            # Login and send
            await client.login(self.token)
            
            # Small delay to ensure we're ready
            await asyncio.sleep(0.5)
            
            channel = client.get_channel(int(self.channel_id))
            
            if not channel:
                print(f"[Discord] ❌ Channel {self.channel_id} not found or inaccessible")
                await client.close()
                return False
            
            print(f"[Discord] 📍 Found channel: {channel.name}")
            await channel.send(embed=embed)
            print(f"[Discord] ✅ Message sent successfully!")
            await client.close()
            return True
            
        except discord.errors.LoginFailure as e:
            print(f"[Discord] ❌ Login failed (invalid token?): {e}")
            return False
        except discord.errors.NotFound as e:
            print(f"[Discord] ❌ Channel not found: {e}")
            return False
        except discord.errors.Forbidden as e:
            print(f"[Discord] ❌ Permission denied: {e}")
            return False
        except Exception as e:
            print(f"[Discord] ❌ Error: {type(e).__name__}: {e}")
            return False
    
    def post_phase_complete(self, phase: str, details: Dict[str, Any]) -> None:
        """Post message when a phase completes"""
        embed = discord.Embed(
            title=f"✅ AutoDJ: {phase} Complete",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        
        for key, value in details.items():
            embed.add_field(name=key, value=str(value), inline=True)
        
        embed.set_footer(text="AutoDJ Pipeline")
        self._send_embed_sync(embed)
    
    def post_playlist(self, transitions: Dict) -> None:
        """Post formatted playlist when generated"""
        tracks = transitions.get('transitions', [])
        duration_sec = transitions.get('mix_duration_seconds', 0)
        duration_str = f"{duration_sec//60}:{duration_sec%60:02d}"
        
        embed = discord.Embed(
            title="🎵 AutoDJ Mix Generated",
            description=f"{len(tracks)} tracks • {duration_str}",
            color=0x1db954,  # Spotify green
            timestamp=datetime.utcnow()
        )
        
        # Add each track with transition type
        for i, track in enumerate(tracks, 1):
            artist = track.get('artist', 'Unknown')
            title = track.get('title', 'Unknown')
            bpm = track.get('bpm', '?')
            key = track.get('key', '?')
            transition = track.get('transition_type', 'blend').upper()
            
            # Build field value
            field_value = f"**{artist}** – {title}\n"
            field_value += f"BPM: {bpm} | Key: {key}"
            
            # Add field (inline=False for full width)
            embed.add_field(
                name=f"{i}. {transition}",
                value=field_value,
                inline=False
            )
        
        embed.set_footer(text="AutoDJ Pipeline")
        self._send_embed_sync(embed)
    
    def post_complete(self, mix_info: Dict[str, Any]) -> None:
        """Post message when entire pipeline completes"""
        embed = discord.Embed(
            title="✅ AutoDJ Pipeline Complete!",
            description="Mix is ready for broadcast",
            color=0x00ff00,  # Green
            timestamp=datetime.utcnow()
        )
        
        for key, value in mix_info.items():
            embed.add_field(name=key, value=str(value), inline=False)
        
        embed.set_footer(text="AutoDJ Pipeline")
        self._send_embed_sync(embed)
    
    def post_error(self, phase: str, error_msg: str, log_path: Optional[str] = None) -> None:
        """Post error notification when pipeline fails"""
        embed = discord.Embed(
            title=f"❌ AutoDJ Failed: {phase}",
            description=error_msg,
            color=0xff0000,  # Red
            timestamp=datetime.utcnow()
        )
        
        if log_path:
            embed.add_field(name="Log File", value=log_path, inline=False)
        
        embed.set_footer(text="AutoDJ Pipeline")
        self._send_embed_sync(embed)
