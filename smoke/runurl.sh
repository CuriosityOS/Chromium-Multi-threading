#!/bin/bash
# usage: runurl.sh URL secs  -> chrome (OMT unless FLAG set) normal window, log smoke/run.log
cd /root/cr153
pkill -f "[u]ser-data-dir=/tmp/omt-url"; sleep 0.5; rm -rf /tmp/omt-url
(DISPLAY=:78 timeout $2 src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-url --no-first-run --enable-logging=stderr --v=0 ${FLAG---enable-blink-features=OffMainThreadRendering} $EXTRA "$1" > smoke/run.log 2>&1 &)
for i in $(seq 1 $2); do sleep 1; echo "t=$i threads=$(ps -eLo comm | grep -c BlinkRenderThr)"; done
sleep 0.5
grep -a "OMT\|CONSOLE\|FATAL\|Received signal" smoke/run.log | grep -v "fallback" | sed "s/.*\] //" | cut -c1-170 | head -${LINES_MAX:-40}
