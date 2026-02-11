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
from datetime import datetime
from typing import Dict, Any, Optional, List


class DiscordNotifier:
    """Posts AutoDJ pipeline status and playlists to Discord"""
    
    def __init__(self):
        """Initialize notifier with token and channel from environment"""
        self.token = os.getenv('DISCORD_TOKEN')
        self.channel_id = os.getenv('DISCORD_CHANNEL_ID')
        self.enabled = bool(self.token and self.channel_id)
        
        if not self.enabled:
            print("[Discord] Notifier disabled (missing TOKEN or CHANNEL_ID)")
    
    async def _send_embed(self, embed: discord.Embed) -> bool:
        """Internal: Send embed to Discord channel
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            client = discord.Client(intents=discord.Intents.default())
            await client.login(self.token)
            channel = client.get_channel(int(self.channel_id))
            
            if not channel:
                print(f"[Discord] Channel {self.channel_id} not found")
                await client.close()
                return False
            
            await channel.send(embed=embed)
            await client.close()
            return True
            
        except Exception as e:
            print(f"[Discord] Error sending embed: {e}")
            return False
    
    def post_phase_start(self, phase: str, estimated_duration: str) -> None:
        """Post message when a phase is starting
        
        Args:
            phase: Phase name (e.g., 'Analyze', 'Generate', 'Render')
            estimated_duration: Estimated time (e.g., '3-5 minutes')
        """
        embed = discord.Embed(
            title=f"🔄 AutoDJ: {phase} Starting...",
            description=f"Estimated duration: {estimated_duration}",
            color=0xffaa00,  # Orange
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="AutoDJ Pipeline")
        
        asyncio.run(self._send_embed(embed))
    
    def post_phase_complete(self, phase: str, details: Dict[str, Any]) -> None:
        """Post message when a phase completes
        
        Args:
            phase: Phase name
            details: Dictionary of phase results
        """
        embed = discord.Embed(
            title=f"✅ AutoDJ: {phase} Complete",
            color=0x00ff00,  # Green
            timestamp=datetime.utcnow()
        )
        
        for key, value in details.items():
            embed.add_field(name=key, value=str(value), inline=True)
        
        embed.set_footer(text="AutoDJ Pipeline")
        asyncio.run(self._send_embed(embed))
    
    def post_playlist(self, transitions: Dict) -> None:
        """Post formatted playlist when generated
        
        Args:
            transitions: Transitions JSON dict from generate_set.py
        """
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
        asyncio.run(self._send_embed(embed))
    
    def post_complete(self, mix_info: Dict[str, Any]) -> None:
        """Post message when entire pipeline completes
        
        Args:
            mix_info: Dictionary with file details
        """
        embed = discord.Embed(
            title="✅ AutoDJ Pipeline Complete!",
            description="Mix is ready for broadcast",
            color=0x00ff00,  # Green
            timestamp=datetime.utcnow()
        )
        
        for key, value in mix_info.items():
            embed.add_field(name=key, value=str(value), inline=False)
        
        embed.set_footer(text="AutoDJ Pipeline")
        asyncio.run(self._send_embed(embed))
    
    def post_error(self, phase: str, error_msg: str, log_path: Optional[str] = None) -> None:
        """Post error notification when pipeline fails
        
        Args:
            phase: Phase where error occurred
            error_msg: Error message
            log_path: Optional path to log file
        """
        embed = discord.Embed(
            title=f"❌ AutoDJ Failed: {phase}",
            description=error_msg,
            color=0xff0000,  # Red
            timestamp=datetime.utcnow()
        )
        
        if log_path:
            embed.add_field(name="Log File", value=log_path, inline=False)
        
        embed.set_footer(text="AutoDJ Pipeline")
        asyncio.run(self._send_embed(embed))
