#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# run.mjs refuses without --build-ready. Operator must first receive parent approval.
exec timeout --signal=TERM --kill-after=10s 17m node run.mjs "$@"
