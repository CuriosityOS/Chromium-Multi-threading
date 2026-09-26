#!/bin/bash
# usage: smoke.sh page.html [seconds] [extra flags]
cd /root/cr153
pgrep -f "Xvfb :78" >/dev/null || (Xvfb :78 -screen 0 1280x800x24 >/dev/null 2>&1 &); sleep 0.5
rm -rf /tmp/omt-prof
DISPLAY=:78 timeout ${2:-12} src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-prof --no-first-run --enable-logging=stderr --v=0 --enable-blink-features=OffMainThreadRendering ${@:3} --app=file:///root/cr153/smoke/$1 > smoke/log.txt 2>&1
echo rc=$?
grep -a "OMT\|FATAL\|Received signal\|CHECK\|^#[0-9]" smoke/log.txt | head -${LINES_MAX:-40}
