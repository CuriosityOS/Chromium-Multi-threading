#!/usr/bin/env python3
"""Dependency-free whitespace formatter/checker; does not claim semantic style linting."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent
failed = []
for path in sorted(root.rglob("*")):
    if any(part in {"results", "preflight", "__pycache__"} for part in path.relative_to(root).parts):
        continue
    if path.suffix not in {".py", ".mjs", ".js", ".sh", ".html", ".css", ".md"}:
        continue
    original = path.read_text()
    formatted = "\n".join(line.rstrip() for line in original.splitlines()).rstrip() + "\n"
    if formatted != original:
        if args.check:
            failed.append(str(path.relative_to(root)))
        else:
            path.write_text(formatted)
if failed:
    raise SystemExit("Whitespace formatting required: " + ", ".join(failed))
print("Format check passed" if args.check else "Whitespace format completed")
