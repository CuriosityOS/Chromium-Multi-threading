#!/bin/sh
# push overlay files to core
cd /Users/core/chromium-threading/overlay && for f in $(find . -type f); do scp -q "$f" "core:/root/cr153/src/$f"; done
