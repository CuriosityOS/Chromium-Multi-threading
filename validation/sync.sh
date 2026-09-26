#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Fixed destination. No --delete; never touch source, build, shared git or old references.
rsync -av --exclude='results/' --exclude='preflight/' --exclude='__pycache__/' \
  "$root/" core:/root/cr153/validation/
