#!/bin/bash
cd /root/cr153
pkill -f "[o]mt-prof2"; sleep 1
(DISPLAY=:78 timeout 14 src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-prof2 --no-first-run --enable-logging=stderr --v=0 --enable-blink-features=OffMainThreadRendering --app=file:///root/cr153/smoke/${1:-b.html} > smoke/log2.txt 2>&1 &)
sleep ${2:-5}
for p in $(pgrep -f "[t]ype=renderer.*omt-prof2"); do if grep -q BlinkRenderThr /proc/$p/task/*/comm 2>/dev/null; then R=$p; fi; done
echo R=$R
gdb -p $R -batch -ex "thread apply all bt 20" 2>/dev/null > smoke/bt.txt
grep -n "^Thread" smoke/bt.txt | head -40
