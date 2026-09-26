#!/bin/bash
# usage: shots.sh page.html "t1 t2 ..." [extra flags]   (feature flag passed via $FLAG)
cd /root/cr153
pgrep -f "Xvfb :78" >/dev/null || (Xvfb :78 -screen 0 1280x800x24 >/dev/null 2>&1 &); sleep 0.5
rm -rf /tmp/omt-prof smoke/shot_*.png
DISPLAY=:78 src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-prof --no-first-run --enable-logging=stderr --v=0 ${FLAG---enable-blink-features=OffMainThreadRendering} ${@:3} --app=file:///root/cr153/smoke/$1 > smoke/log.txt 2>&1 &
PID=$!
start=$(date +%s.%N)
for t in $2; do
  while (( $(echo "$(date +%s.%N) - $start < $t" | bc) )); do sleep 0.02; done
  DISPLAY=:78 ffmpeg -loglevel error -f x11grab -video_size 1280x800 -i :78 -frames:v 1 smoke/shot_$t.png -y
done
kill $PID; sleep 0.5; pkill -f omt-prof
grep -a "FATAL\|Received signal" smoke/log.txt | head -5
