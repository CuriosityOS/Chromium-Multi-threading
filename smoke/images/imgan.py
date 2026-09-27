# usage: imgan.py video.mkv [fps]  -> every 0.25 s: bounding boxes of the test colors
import sys, subprocess, numpy as np
w, h = 1280, 800
fps = float(sys.argv[2]) if len(sys.argv) > 2 else 30
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", sys.argv[1], "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
n = len(raw) // (w * h * 3)
a = np.frombuffer(raw, np.uint8)[: n * w * h * 3].reshape(n, h, w, 3).astype(int)
colors = {"cyan": (0, 255, 255), "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 160, 0), "magenta": (255, 0, 255), "yellow": (255, 255, 0)}
step = max(1, int(fps / 4))
prev = None
for i in range(0, n, step):
    f = a[i]
    parts = []
    for name, c in colors.items():
        m = (abs(f[:, :, 0] - c[0]) < 30) & (abs(f[:, :, 1] - c[1]) < 30) & (abs(f[:, :, 2] - c[2]) < 30)
        ys, xs = np.nonzero(m)
        parts.append(f"{name}=" + (f"{xs.max()-xs.min()+1}x{ys.max()-ys.min()+1}@{xs.min()},{ys.min()}" if len(xs) else "-"))
    line = " ".join(parts)
    if line != prev:
        print(f"{i/fps:5.2f}s {line}")
        prev = line
