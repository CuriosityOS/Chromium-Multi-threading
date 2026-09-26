#!/usr/bin/env python3
"""Return viewport-to-X11 translation from matching solid-color proof panels."""
import argparse
import json
from pathlib import Path

from analyze import image_alignment

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cdp", type=Path)
    parser.add_argument("x11", type=Path)
    args = parser.parse_args()
    print(json.dumps(image_alignment(args.cdp, args.x11)))
