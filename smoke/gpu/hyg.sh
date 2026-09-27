#!/bin/bash
# usage: hyg.sh page secs label  -- like hy.sh but on the RTX 4090 Xorg display :20 (real GPU)
cd /root/cr153
P=/tmp/omt-hyg
rm -rf $P smoke/hyg-$3.mkv
export DISPLAY=:20
ffmpeg -loglevel error -f x11grab -framerate 60 -video_size 1280x800 -draw_mouse 0 -i :20+0,0 -t $(( $2 + 1 )) -c:v ffv1 smoke/hyg-$3.mkv &
FF=$!
( sleep 3; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader; nvidia-smi pmon -c 1 2>/dev/null | grep -i chrome ) > smoke/hyg-$3.gpu 2>&1 &
timeout $2 src/out/Omt/chrome --no-sandbox --user-data-dir=$P --no-first-run --no-default-browser-check --enable-logging=stderr --v=0 --window-position=0,0 --window-size=1280,800 --force-device-scale-factor=1 --ozone-platform=x11 ${FLAG---enable-blink-features=OffMainThreadRendering} ${EXTRA} --app=file:///root/cr153/smoke/$1 > smoke/hyg-$3.log 2>&1
wait $FF
