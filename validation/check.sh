#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p preflight
export TMPDIR="$PWD/preflight"
python3 format.py --check
python3 lint.py
for source in ./*.mjs ./demo/*.js; do node --check "$source"; done
for source in ./*.sh; do bash -n "$source"; done
if command -v shellcheck >/dev/null; then
  shellcheck ./*.sh
else
  printf '%s\n' 'shellcheck unavailable; bash syntax checked (no installation attempted).'
fi
python3 -m unittest -v test_validation.py test_extended.py
node --test test_cdp.mjs test_build.mjs test_pointer.mjs test_readiness.mjs test_display.mjs
printf '%s\n' 'PASS: static checks and evidence unit tests; Chromium NOT launched.'
