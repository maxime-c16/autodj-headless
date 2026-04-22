"""
Pytest configuration for autodj-headless test suite.

Adds `src/` to sys.path so internal modules that use
`from autodj.xxx import ...` (without the `src.` prefix)
can be imported when tests run from the project root.
"""

import sys
from pathlib import Path

# Project root is one level up from this conftest.py
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
