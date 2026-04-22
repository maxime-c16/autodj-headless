"""
Intra-Track EQ Automation Selector.

Extends the greedy selector to make intelligent decisions about where to apply
EQ cuts/filters within a track (not during transitions).

Per § 5.4 (intra-track mixing):
- Detects musically logical cut points (post-drop, mid-breakdown, pre-outro)
- Confidence scoring: only apply cuts when analysis is high-confidence
- Envelope control: define attack/hold/release for smooth curves
"""

import logging
from typing import List, Dict, Any, Optional
import json

logger = logging.getLogger(__name__)


class EQCutOpportunity:
    """Represents a potential EQ cut in a track."""

    def __init__(
        self,
        bar: int,
        cut_type: str,
        filter_params: Dict[str, Any],
        envelope: Dict[str, Any],
        confidence: float,
        section: Optional[str] = None,
    ):
        """
        Initialize EQ cut opportunity.

        Args:
            bar: Starting bar number (0-indexed)
            cut_type: Type of cut ("bass_tension", "vocal_clarity", "punchy_tension", etc.)
            filter_params: Filter definition (type, freq, q, gain)
            envelope: Attack/hold/release definition in ms and bars
            confidence: Score 0.0-1.0 indicating reliability
            section: Section name (e.g., "breakdown", "drop")
        """
        self.bar = bar
        self.cut_type = cut_type
        self.filter_params = filter_params
        self.envelope = envelope
        self.confidence = confidence
        self.section = section

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "bar": self.bar,
            "cut_type": self.cut_type,
            "filter": self.filter_params,
            "envelope": self.envelope,
            "confidence": self.confidence,
            "section": self.section,
        }


class IntraTrackEQSelector:
    """
    Intelligent intra-track EQ decision maker.

    Analyzes track structure (sections, energy, vocals) and recommends EQ cuts
    at musically logical points.
    """

    def __init__(self, min_confidence: float = 0.75):
        """
        Initialize selector.

        Args:
            min_confidence: Minimum confidence to include a cut (0.0-1.0)
        """
        self.min_confidence = min_confidence
        logger.info(f"IntraTrackEQSelector initialized (min_confidence={min_confidence})")

    def analyze_track(
        self, track_analysis: Dict[str, Any], track_audio_data: Optional[Dict[str, Any]] = None
    ) -> List[EQCutOpportunity]:
        """
        Analyze track and identify EQ cut opportunities.
        
        Pro DJ mode: Aggressive detection to find cuts on almost every track.
        These are standard mixing moves applied frequently for engagement.

        Args:
            track_analysis: Track analysis dict (from track_analysis table)
            track_audio_data: Optional audio metadata (energy, spectral, etc.)

        Returns:
            List of EQCutOpportunity objects, sorted by bar number
        """
        opportunities = []

        # Parse analysis
        sections = self._parse_json_field(track_analysis, "sections_json", {})
        energy_profile = self._parse_json_field(track_analysis, "energy_profile_json", {})
        has_vocal = track_analysis.get("has_vocal", 0) == 1
        total_bars = track_analysis.get("total_bars", 0)

        logger.debug(
            f"Analyzing track: sections={len(sections)}, vocal={has_vocal}, bars={total_bars}"
        )

        # Rule 1: Bass cut in breakdown (tension building) - RELAXED
        # Pro DJs always do this when the energy softens
        if breakdown := self._find_section(sections, "breakdown"):
            breakdown_duration = breakdown.get("duration_bars", 0)
            # Relaxed: trigger on ANY breakdown, not just long ones
            if breakdown_duration > 4:  # Down from 12 bars
                opp = EQCutOpportunity(
                    bar=breakdown.get("start_bar", 0) + 4,
                    cut_type="bass_tension",
                    filter_params={"type": "low_pass", "freq": 100, "q": 1.0},
                    envelope={
                        "attack_ms": 1000,
                        "hold_bars": 4,  # Down from 6 for faster cycling
                        "release_ms": 3000,
                        "curve": "sine",
                    },
                    confidence=0.90,
                    section="breakdown",
                )
                opportunities.append(opp)
                logger.debug(f"Identified bass_tension at bar {opp.bar}")

        # Rule 2: Punchy pre-drop (2-4 bars before drop) - RELAXED
        # Essential for building tension before a build/drop
        if drop := self._find_section(sections, "drop"):
            drop_start = drop.get("start_bar", 0)
            if drop_start > 0:  # Even if drop starts at bar 0 (rare), still try
                opp = EQCutOpportunity(
                    bar=max(0, drop_start - 2),  # 2 bars before, or start of track
                    cut_type="punchy_tension",
                    filter_params={"type": "low_pass", "freq": 80, "q": 1.2},
                    envelope={
                        "attack_ms": 100,
                        "hold_bars": 0.5,
                        "release_ms": 200,
                        "curve": "sharp",
                    },
                    confidence=0.85,
                    section="pre-drop",
                )
                opportunities.append(opp)
                logger.debug(f"Identified punchy_tension at bar {opp.bar}")

        # Rule 3: Vocal clarity (mid scoop during vocals) - ALWAYS APPLY IF VOCALS DETECTED
        # Standard move to make vocals cut through
        if has_vocal:
            opp = EQCutOpportunity(
                bar=4,  # Start earlier (bar 4 instead of 8)
                cut_type="vocal_clarity",
                filter_params={"type": "band_stop", "freq": 400, "q": 1.5, "gain": -4},
                envelope={
                    "attack_ms": 300,
                    "hold_bars": 16,  # Longer hold since vocals are prominent
                    "release_ms": 800,
                    "curve": "sine",
                },
                confidence=0.85,  # Up from 0.70 - if has_vocal=1, do it
                section="vocal_region",
            )
            opportunities.append(opp)
            logger.debug(f"Identified vocal_clarity at bar {opp.bar}")

        # Rule 4: Mid-buildup energy boost (peak energy point)
        # Pro DJs often cut bass mid-track to add tension, then drop it back
        if total_bars > 16:
            mid_point = total_bars // 2
            opp = EQCutOpportunity(
                bar=max(8, mid_point - 4),  # A bit before midpoint
                cut_type="mid_buildup",
                filter_params={"type": "low_pass", "freq": 120, "q": 0.9},
                envelope={
                    "attack_ms": 800,
                    "hold_bars": 3,
                    "release_ms": 1500,
                    "curve": "sine",
                },
                confidence=0.75,
                section="mid_track",
            )
            opportunities.append(opp)
            logger.debug(f"Identified mid_buildup at bar {opp.bar}")

        # Rule 5: High-pass filter swells (standard DJ drop technique)
        # Cut lows, then slowly bring them back for impact
        if drop := self._find_section(sections, "drop"):
            drop_start = drop.get("start_bar", 0)
            drop_duration = drop.get("duration_bars", 0)
            # If drop is long enough, add a high-pass at the beginning
            if drop_duration > 8:
                opp = EQCutOpportunity(
                    bar=drop_start,
                    cut_type="drop_isolation",
                    filter_params={"type": "high_pass", "freq": 150, "q": 0.7},
                    envelope={
                        "attack_ms": 200,
                        "hold_bars": 2,
                        "release_ms": 2000,
                        "curve": "sine",
                    },
                    confidence=0.80,
                    section="drop_start",
                )
                opportunities.append(opp)
                logger.debug(f"Identified drop_isolation at bar {opp.bar}")

        # Rule 6: Post-drop bass restoration (energy recovery)
        # 4-8 bars after drop, bring bass back to restore impact
        if drop := self._find_section(sections, "drop"):
            drop_start = drop.get("start_bar", 0)
            drop_duration = drop.get("duration_bars", 0)
            if drop_duration > 0:
                # Apply 4-8 bars after drop start
                bass_restore_bar = drop_start + drop_duration + 4
                if bass_restore_bar < total_bars:
                    opp = EQCutOpportunity(
                        bar=bass_restore_bar,
                        cut_type="bass_restore",
                        filter_params={"type": "low_pass", "freq": 90, "q": 1.1},
                        envelope={
                            "attack_ms": 500,
                            "hold_bars": 4,
                            "release_ms": 2500,
                            "curve": "sine",
                        },
                        confidence=0.80,
                        section="post_drop",
                    )
                    opportunities.append(opp)
                    logger.debug(f"Identified bass_restore at bar {bass_restore_bar}")

        # Rule 7: Outro energy dip (wind-down technique)
        # If track is long, cut energy near the end for smooth transition
        if total_bars > 20:
            outro_start = max(0, total_bars - 16)  # Last 16 bars
            if outro_start > 0:
                opp = EQCutOpportunity(
                    bar=outro_start,
                    cut_type="outro_prep",
                    filter_params={"type": "low_pass", "freq": 110, "q": 0.95},
                    envelope={
                        "attack_ms": 1200,
                        "hold_bars": 6,
                        "release_ms": 2000,
                        "curve": "sine",
                    },
                    confidence=0.75,
                    section="outro",
                )
                opportunities.append(opp)
                logger.debug(f"Identified outro_prep at bar {outro_start}")

        # Rule 8: Mid-intro bass boost (grab attention immediately)
        # Very first bars: bass presence to hook the listener
        if total_bars > 8:
            opp = EQCutOpportunity(
                bar=2,
                cut_type="intro_presence",
                filter_params={"type": "low_pass", "freq": 110, "q": 1.0},
                envelope={
                    "attack_ms": 400,
                    "hold_bars": 3,
                    "release_ms": 1000,
                    "curve": "sine",
                },
                confidence=0.75,
                section="intro",
            )
            opportunities.append(opp)
            logger.debug(f"Identified intro_presence at bar 2")

        # Filter by confidence (very lenient now)
        filtered = [o for o in opportunities if o.confidence >= self.min_confidence]
        logger.info(f"Found {len(filtered)} EQ opportunities (confidence >= {self.min_confidence})")

        return sorted(filtered, key=lambda x: x.bar)

    def select_cuts(
        self, opportunities: List[EQCutOpportunity], strategy: str = "moderate"
    ) -> List[EQCutOpportunity]:
        """
        Select which cuts to apply based on strategy.

        Args:
            opportunities: List of EQCutOpportunity objects
            strategy: "baseline" (none), "conservative" (high confidence), 
                      "moderate" (top 2-3), "aggressive" (all)

        Returns:
            Filtered list of opportunities to apply
        """
        if strategy == "baseline":
            return []

        elif strategy == "conservative":
            return [o for o in opportunities if o.confidence > 0.90]

        elif strategy == "moderate":
            # Pick best 2-3 cuts
            return opportunities[:3] if len(opportunities) > 3 else opportunities

        elif strategy == "aggressive":
            # Apply all
            return opportunities

        else:
            logger.warning(f"Unknown strategy: {strategy}, defaulting to conservative")
            return [o for o in opportunities if o.confidence > 0.90]

    @staticmethod
    def _parse_json_field(data: Dict[str, Any], field: str, default: Any = None) -> Any:
        """Safely parse JSON field."""
        value = data.get(field)
        if not value:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        return value

    @staticmethod
    def _find_section(sections: Dict[str, Any], section_type: str) -> Optional[Dict[str, Any]]:
        """Find a specific section by type."""
        if isinstance(sections, dict):
            for label, details in sections.items():
                if details.get("label") == section_type:
                    return details
        return None
