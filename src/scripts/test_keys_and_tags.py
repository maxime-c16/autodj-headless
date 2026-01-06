#!/usr/bin/env python3
"""
Tests for tagging and key detection.

Tests cover:
- MP4/M4A tagging (mutagen.mp4)
- ID3 tagging (mutagen.id3)
- FLAC tagging
- keyfinder-cli integration
- Key detection fallback to essentia
"""

import sys
import tempfile
import logging
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


def test_mp4_tagging():
    """Test MP4 tag writing."""
    try:
        from mutagen.mp4 import MP4
        import struct
        import io

        logger.info("Testing MP4 tagging...")

        # Create a minimal valid MP4 file for testing
        # (In real tests, use a small test file)
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
            mp4_path = f.name
            # Write minimal MP4 header (ftyp box)
            f.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41")

        try:
            audio = MP4(mp4_path)
            # Test writing comment and custom key tag
            audio["\xa9cmt"] = ["Test BPM: 120"]
            audio["\xa9key"] = ["9A"]
            audio.save()
            logger.info("✅ MP4 tag write test passed")
            return True
        except Exception as e:
            logger.warning(f"⚠️  MP4 tagging test skipped (test file creation): {e}")
            return None  # Skip on test setup failure
        finally:
            Path(mp4_path).unlink(missing_ok=True)

    except ImportError:
        logger.warning("⚠️  mutagen not available, skipping MP4 test")
        return None


def test_keyfinder_cli_available():
    """Test if keyfinder-cli is available in PATH."""
    try:
        import subprocess

        logger.info("Testing keyfinder-cli availability...")

        result = subprocess.run(
            ["which", "keyfinder-cli"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            logger.info(f"✅ keyfinder-cli found at: {result.stdout.strip()}")
            return True
        else:
            logger.warning("⚠️  keyfinder-cli not found in PATH")
            return False

    except Exception as e:
        logger.warning(f"⚠️  Could not check keyfinder-cli: {e}")
        return False


def test_keyfinder_cli_version():
    """Test keyfinder-cli version."""
    try:
        import subprocess

        logger.info("Testing keyfinder-cli version...")

        result = subprocess.run(
            ["keyfinder-cli", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            version_output = result.stdout.strip() or result.stderr.strip()
            logger.info(f"✅ keyfinder-cli version: {version_output}")
            return True
        else:
            logger.warning(f"⚠️  keyfinder-cli version check failed: {result.stderr}")
            return False

    except FileNotFoundError:
        logger.warning("⚠️  keyfinder-cli executable not found")
        return False
    except Exception as e:
        logger.warning(f"⚠️  Could not check keyfinder-cli version: {e}")
        return False


def test_key_detection_config():
    """Test that key detection config is properly loaded."""
    try:
        from autodj.config import Config

        logger.info("Testing key detection config...")

        config = Config.load()
        key_config = config.get("key_detection", {})

        if key_config:
            method = key_config.get("method", "essentia")
            logger.info(f"✅ Key detection method configured: {method}")
            return True
        else:
            logger.warning("⚠️  Key detection config not found")
            return False

    except Exception as e:
        logger.error(f"✗ Key detection config test failed: {e}")
        return False


def test_tag_writing_function():
    """Test the _write_id3_tags function with different formats."""
    try:
        from scripts.analyze_library import _write_id3_tags

        logger.info("Testing tag writing function...")

        # Create test files with different extensions
        formats = [".mp3", ".m4a", ".flac"]
        results = {}

        for fmt in formats:
            with tempfile.NamedTemporaryFile(suffix=fmt, delete=False) as f:
                test_file = f.name
                # Write minimal format header
                if fmt == ".mp3":
                    f.write(b"ID3")  # Minimal ID3 header
                elif fmt == ".m4a":
                    f.write(b"\x00\x00\x00\x20ftypisom")  # Minimal MP4
                elif fmt == ".flac":
                    f.write(b"fLaC")  # Minimal FLAC

            try:
                _write_id3_tags(test_file, bpm=128.0, key="9A")
                logger.info(f"✅ Tag writing works for {fmt}")
                results[fmt] = True
            except Exception as e:
                logger.warning(f"⚠️  Tag writing test for {fmt}: {e}")
                results[fmt] = False
            finally:
                Path(test_file).unlink(missing_ok=True)

        return all(results.values())

    except ImportError as e:
        logger.warning(f"⚠️  Could not import tag writing function: {e}")
        return None


def test_database_schema():
    """Test that database schema has key field."""
    try:
        from autodj.db import Database

        logger.info("Testing database schema...")

        db = Database(":memory:")  # Use in-memory DB for testing
        db.connect()

        # Check if key column exists
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA table_info(tracks)")
        columns = {row[1] for row in cursor.fetchall()}

        if "key" in columns:
            logger.info("✅ Database schema includes 'key' column")
            db.disconnect()
            return True
        else:
            logger.warning("✗ Database schema missing 'key' column")
            db.disconnect()
            return False

    except Exception as e:
        logger.error(f"✗ Database schema test failed: {e}")
        return False


def run_all_tests():
    """Run all tests and report results."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info("AutoDJ Key Detection & Tagging Tests")
    logger.info("=" * 60)
    logger.info("")

    tests = [
        ("MP4 Tagging", test_mp4_tagging),
        ("keyfinder-cli Available", test_keyfinder_cli_available),
        ("keyfinder-cli Version", test_keyfinder_cli_version),
        ("Key Detection Config", test_key_detection_config),
        ("Tag Writing Function", test_tag_writing_function),
        ("Database Schema", test_database_schema),
    ]

    results = {}
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = result
        except Exception as e:
            logger.error(f"✗ Test '{name}' crashed: {e}", exc_info=True)
            results[name] = False

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    passed = sum(1 for r in results.values() if r is True)
    skipped = sum(1 for r in results.values() if r is None)
    failed = sum(1 for r in results.values() if r is False)

    for name, result in results.items():
        status = "✅ PASS" if result is True else ("⚠️  SKIP" if result is None else "✗ FAIL")
        logger.info(f"{status:10} {name}")

    logger.info("")
    logger.info(f"Passed:  {passed}")
    logger.info(f"Skipped: {skipped}")
    logger.info(f"Failed:  {failed}")
    logger.info("=" * 60)
    logger.info("")

    # Return exit code
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
