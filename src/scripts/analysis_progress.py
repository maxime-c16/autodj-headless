#!/usr/bin/env python3
"""Small CLI to print analysis progress (query DB).

Usage:
  python -m src.scripts.analysis_progress
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database


def main():
    db = Database()
    db.connect()
    prog = db.get_analysis_progress()
    db.disconnect()
    print(json.dumps(prog, indent=2))


if __name__ == "__main__":
    main()
