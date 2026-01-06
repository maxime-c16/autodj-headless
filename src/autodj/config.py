"""
Configuration management for AutoDJ-Headless.

Loads and validates TOML config against strict bounds defined in SPEC.md.
All tunable parameters are bounded and validated at startup.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import toml
import logging

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when config validation fails."""
    pass


class Config:
    """Configuration loader and validator."""

    # Parameter bounds from SPEC.md § 8
    PARAM_BOUNDS = {
        "mix": {
            "target_duration_minutes": (30, 120),
            "max_playlist_tracks": (10, 150),
        },
        "constraints": {
            "bpm_tolerance_percent": (2.0, 10.0),
            "energy_window_size": (2, 5),
            "min_track_duration_seconds": (60, 300),
            "max_track_duration_seconds": (300, 3600),
            "max_repeat_decay_hours": (24, 720),
        },
        "analysis": {
            "aubio_hop_size": (256, 2048),
            "aubio_buf_size": (2048, 8192),
            "bpm_search_range": None,  # List type
            "confidence_threshold": (0.0, 1.0),
        },
        "key_detection": {
            "window_size": (1024, 8192),
        },
        "render": {
            "crossfade_duration_seconds": (2, 8),
            "mp3_bitrate": (128, 320),
        },
    }

    DEFAULT_CONFIG = {
        "config_version": "1.0",
        "mix": {
            "target_duration_minutes": 60,
            "max_playlist_tracks": 90,
            "seed_track_path": "",
        },
        "constraints": {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_track_duration_seconds": 1200,  # 20 minutes
            "max_repeat_decay_hours": 168,
        },
        "analysis": {
            "aubio_hop_size": 512,
            "aubio_buf_size": 4096,
            "bpm_search_range": [50, 200],
            "confidence_threshold": 0.5,
        },
        "key_detection": {
            "method": "essentia",
            "window_size": 4096,
        },
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 192,
            "crossfade_duration_seconds": 4,
            "time_stretch_quality": "high",
            "enable_ladspa_eq": False,
        },
    }

    def __init__(self, config_dict: Dict[str, Any]):
        """Initialize config from dictionary."""
        self.data = config_dict
        self._validate()

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """
        Load config from TOML file.

        Args:
            config_path: Path to autodj.toml. If None, uses AUTODJ_CONFIG_PATH env var
                        or defaults to configs/autodj.toml.

        Returns:
            Config instance.

        Raises:
            ConfigError: If config is invalid or missing.
        """
        if config_path is None:
            config_path = os.getenv("AUTODJ_CONFIG_PATH", "configs/autodj.toml")

        config_path = Path(config_path)

        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}. Using defaults.")
            return cls(cls.DEFAULT_CONFIG.copy())

        try:
            config_dict = toml.load(config_path)
            logger.info(f"Loaded config from {config_path}")
            return cls(config_dict)
        except Exception as e:
            raise ConfigError(f"Failed to load config from {config_path}: {e}")

    def _validate(self) -> None:
        """
        Validate all config parameters against bounds in SPEC.md.

        Raises:
            ConfigError: If any parameter is out of bounds.
        """
        for section, params in self.PARAM_BOUNDS.items():
            if section not in self.data:
                logger.warning(f"Missing config section: {section}. Using defaults.")
                self.data[section] = self.DEFAULT_CONFIG.get(section, {})
                continue

            section_data = self.data[section]

            for param, bounds in params.items():
                if param not in section_data:
                    default_val = self.DEFAULT_CONFIG.get(section, {}).get(param)
                    if default_val is not None:
                        logger.warning(f"Missing param {section}.{param}. Using default: {default_val}")
                        section_data[param] = default_val
                    continue

                value = section_data[param]

                # Handle list types (no bounds check needed)
                if bounds is None:
                    continue

                # Handle numeric ranges
                if isinstance(bounds, tuple) and len(bounds) == 2:
                    min_val, max_val = bounds
                    if not (min_val <= value <= max_val):
                        raise ConfigError(
                            f"Parameter {section}.{param}={value} out of bounds "
                            f"[{min_val}, {max_val}]"
                        )

        logger.info("✅ Config validation passed")

    def get(self, section: str, param: str, default: Any = None) -> Any:
        """Get a config parameter safely."""
        return self.data.get(section, {}).get(param, default)

    def __getitem__(self, section: str) -> Dict[str, Any]:
        """Allow dict-like access: config["mix"]"""
        return self.data.get(section, {})

    def __repr__(self) -> str:
        version = self.data.get('config_version', 'unknown')
        return f"Config(version={version})"
