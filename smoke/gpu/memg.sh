#!/bin/bash
# usage: mem.sh page secs label ; samples renderer PSS every 2s -> smoke/mem-<label>.tsv
cd /root/cr153
pkill -f "[u]ser-data-dir=/tmp/omt-mem" ; sleep 0.5; rm -rf /tmp/omt-mem
pgrep -f "Xvfb :78" >/dev/null || (Xvfb :78 -screen 0 1280x800x24 >/dev/null 2>&1 &); sleep 0.3
(DISPLAY=:20 timeout $2 src/out/Omt/chrome --no-sandbox --user-data-dir=/tmp/omt-mem --no-first-run --window-position=0,0 --window-size=1280,800 --ozone-platform=x11 --enable-logging=stderr --v=0 ${FLAG---enable-blink-features=OffMainThreadRendering} --app="file:///root/cr153/smoke/$1" > smoke/mem-$3.log 2>&1 &)
out=smoke/mem-$3.tsv; : > $out
for i in $(seq 1 $(( $2 / 2 - 1 ))); do
  sleep 2
  b=$(pgrep -f "[u]ser-data-dir=/tmp/omt-mem" | head -1)
  best=0; bt=0
  for p in $(pgrep -f "[t]ype=renderer"); do
    # descendant of our browser?
    a=$p; ok=0; for k in 1 2 3 4 5; do a=$(ps -o ppid= -p $a 2>/dev/null | tr -d " "); [ -z "$a" ] && break; if pgrep -f "[u]ser-data-dir=/tmp/omt-mem" | grep -qx "$a"; then ok=1; break; fi; done
    [ $ok = 1 ] || continue
    pss=$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup 2>/dev/null)
    [ -n "$pss" ] && [ $pss -gt $best ] && { best=$pss; bt=$(grep -l BlinkRenderThre /proc/$p/task/*/comm 2>/dev/null | wc -l); rp=$p; }
  done
  gpu=0; for p in $(pgrep -f "[t]ype=gpu-process"); do g=$(awk "/^Pss:/{print \$2}" /proc/$p/smaps_rollup 2>/dev/null); [ -n "$g" ] && gpu=$((gpu+g)); done
  v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); echo -e "$((i*2))\t$best\t$bt\t$gpu\t$v" >> $out
done
sleep 1.5
