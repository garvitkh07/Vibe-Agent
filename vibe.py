#!/usr/bin/env python3
"""Convenience launcher:  python vibe.py  ==  python -m vibe_agent"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vibe_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
