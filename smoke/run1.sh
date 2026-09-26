#!/bin/bash
# usage: run1.sh page secs [actions-script]   ; runs chrome with OMT flag (or $FLAG) under Xvfb :78, log to smoke/run.log
cd /root/cr153
pkill -f "[u]ser-data-dir=/tmp/omt-run" ; sleep 0.5; rm -rf /tmp/omt-run
pgrep -f "Xvfb :78" >/dev/null || (Xvfb :78 -screen 0 1280x800x24 >/dev/null 2>&1 &); sleep 0.3
(DISPLAY=:78 timeout $2 src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-run --no-first-run --enable-logging=stderr --v=0 ${FLAG---enable-blink-features=OffMainThreadRendering} ${EXTRA} --app=${URLBASE:-file:///root/cr153/smoke/}$1 > smoke/run.log 2>&1 &)
if [ -n "$3" ]; then bash -c "$3"; fi
sleep $2; sleep 0.5
grep -a "OMT\|CONSOLE\|FATAL\|Received signal" smoke/run.log | sed "s/.*\] //" | grep -v "fallback stack" | cut -c1-170 | head -${LINES_MAX:-40}
