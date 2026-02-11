"""
AutoDJ Discord Notifier - Posts pipeline status to Discord via REST API

Uses Discord API directly (no discord.py library needed inside container)
"""

import os
import requests
import json
from datetime import datetime
from typing import Dict, Any, Optional


class DiscordNotifier:
    """Posts AutoDJ pipeline status to Discord using REST API"""
    
    def __init__(self):
        """Initialize notifier with token and channel from environment"""
        self.token = os.getenv('DISCORD_TOKEN')
        self.channel_id = os.getenv('DISCORD_CHANNEL_ID')
        self.enabled = bool(self.token and self.channel_id)
        self.api_url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
        
        if not self.enabled:
            print("[Discord] ⚠️  Notifier disabled (missing TOKEN or CHANNEL_ID)")
    
    def _send_embed(self, title: str, description: str, color: int, fields: Dict[str, str]) -> bool:
        """Send embed via Discord REST API
        
        Args:
            title: Embed title
            description: Embed description
            color: Embed color (0xRRGGBB)
            fields: Dict of field names to values
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            print(f"[Discord] 📤 Sending message to channel {self.channel_id}...")
            
            # Build embed
            embed = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "fields": [
                    {"name": k, "value": str(v), "inline": True}
                    for k, v in fields.items()
                ],
                "footer": {"text": "AutoDJ Pipeline"}
            }
            
            # Prepare request
            headers = {
                "Authorization": f"Bot {self.token}",
                "Content-Type": "application/json"
            }
            payload = {"embeds": [embed]}
            
            # Send to Discord API
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 204 or response.status_code == 200:
                print(f"[Discord] ✅ Message sent successfully!")
                return True
            else:
                error_text = response.text[:200] if response.text else "Unknown error"
                print(f"[Discord] ❌ Failed ({response.status_code}): {error_text}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            print(f"[Discord] ❌ Connection error: {e}")
            return False
        except requests.exceptions.Timeout:
            print(f"[Discord] ❌ Request timeout")
            return False
        except Exception as e:
            print(f"[Discord] ❌ Error: {type(e).__name__}: {e}")
            return False
    
    def post_phase_complete(self, phase: str, details: Dict[str, Any]) -> None:
        """Post message when a phase completes"""
        self._send_embed(
            title=f"✅ AutoDJ: {phase} Complete",
            description=f"Pipeline phase completed successfully",
            color=0x00ff00,  # Green
            fields=details
        )
    
    def post_playlist(self, transitions: Dict) -> None:
        """Post formatted playlist when generated"""
        tracks_list = transitions.get('transitions', [])
        duration_sec = transitions.get('mix_duration_seconds', 0)
        duration_str = f"{duration_sec//60}:{duration_sec%60:02d}"
        
        # Build field content
        fields = {}
        for i, track in enumerate(tracks_list[:7], 1):  # Max 7 tracks shown
            artist = track.get('artist', 'Unknown')
            title = track.get('title', 'Unknown')
            bpm = track.get('bpm', '?')
            key = track.get('key', '?')
            
            field_name = f"{i}. {artist[:20]}"
            field_value = f"{title[:30]}\nBPM: {bpm} | Key: {key}"
            fields[field_name] = field_value
        
        # Add summary
        fields['Duration'] = duration_str
        fields['Tracks'] = str(len(tracks_list))
        
        self._send_embed(
            title="🎵 AutoDJ Mix Generated",
            description=f"{len(tracks_list)} tracks • {duration_str}",
            color=0x1db954,  # Spotify green
            fields=fields
        )
    
    def post_complete(self, mix_info: Dict[str, Any]) -> None:
        """Post message when entire pipeline completes"""
        self._send_embed(
            title="✅ AutoDJ Pipeline Complete!",
            description="Mix is ready for broadcast",
            color=0x00ff00,  # Green
            fields=mix_info
        )
    
    def post_error(self, phase: str, error_msg: str, log_path: Optional[str] = None) -> None:
        """Post error notification when pipeline fails"""
        fields = {'Error': error_msg}
        if log_path:
            fields['Log File'] = log_path
        
        self._send_embed(
            title=f"❌ AutoDJ Failed: {phase}",
            description=error_msg,
            color=0xff0000,  # Red
            fields=fields
        )
