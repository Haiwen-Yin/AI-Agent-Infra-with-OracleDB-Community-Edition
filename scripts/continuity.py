#!/usr/bin/env python3
"""Package entrypoint: python scripts/continuity.py --help."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from lib.continuity_cli import main

if __name__=='__main__':
    raise SystemExit(main())
