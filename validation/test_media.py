#!/usr/bin/env python3
"""Synthetic media integration test. No Chromium; these movies are NOT rendering evidence."""
import json
import subprocess
import time
from pathlib import Path

from analyze import CYAN, YELLOW, analyze_pixels, image_alignment
from extended_analysis import lifecycle_pixels

root = Path(__file__).resolve().parent
output = root / "preflight" / f"synthetic-media-{time.time_ns()}"
output.mkdir(parents=True)
width, height, fps = 1280, 800, 15
start_ms = int(time.time() * 1000)
black_row = bytes(width * 3)
cyan_row = bytes(100 * 3) + CYAN * 528 + bytes(72 * 3) + CYAN * 528 + bytes(52 * 3)
yellow_row = bytes(100 * 3) + YELLOW * 528 + bytes(72 * 3) + YELLOW * 528 + bytes(52 * 3)
results = []
for mode in ("baseline", "omt"):
    directory = output / mode
    directory.mkdir()
    arguments = [
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0",
        "-c:v", "ffv1", "-level", "3", "-threads", "2", "-pix_fmt", "bgr0",
        "-enc_time_base", "1:1000", "-output_ts_offset", str(start_ms / 1000), str(directory / "capture.mkv"),
    ]
    with (directory / "ffmpeg.log").open("wb") as log:
        encoder = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            for index in range(5 * fps + 1):
                elapsed = index / fps
                panel = 24
                if mode == "omt":
                    panel += round(240 * max(0, min(1, (elapsed - 1) / 2.4)))
                elif elapsed > 4.2:
                    panel = 264
                encoder.stdin.write(black_row * 200 + cyan_row * panel + yellow_row * 24 + black_row * (height - 224 - panel))
            encoder.stdin.close()
            if encoder.wait(timeout=30):
                raise RuntimeError(f"Synthetic encoder failed; see {directory}")
        finally:
            if encoder.poll() is None:
                encoder.kill()
                encoder.wait()
    case = {
        "synthetic": True,
        "mode": mode,
        "ms": 3000,
        "captureStartedMs": start_ms,
        "block": {
            "start": {"epochMs": start_ms + 1000, "perfMs": 1000},
            "end": {"epochMs": start_ms + 4000, "perfMs": 4000},
            "heartbeatBefore": 10,
            "heartbeatAfter": 10,
        },
    }
    (directory / "case.json").write_text(json.dumps(case, indent=2) + "\n")
    first = analyze_pixels(directory, case)
    second = analyze_pixels(directory, case, 1)
    assert first["heightRangePx"] == second["heightRangePx"]
    assert second["roi"]["x"] == 1180
    assert image_alignment(directory / "capture-pre.png", directory / "capture-pre.png") == {"x": 0, "y": 0}
    results.append({"mode": mode, **first, "secondPanel": second})
lifecycle = output / "bfcache-pixels"
lifecycle.mkdir()
for name, panel in (("owner-a", 64), ("owner-b", 24), ("restored-a", 64), ("restored-mutated-a", 96)):
    pixels = black_row * 200 + cyan_row * panel + yellow_row * 24 + black_row * (height - 224 - panel)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-video_size", f"{width}x{height}", "-i", "pipe:0", "-frames:v", "1", "-threads", "1", str(lifecycle / f"{name}-x11.png")], input=pixels, check=True, timeout=30)
result = {"passed": True, "syntheticOnly": True, "chromiumLaunched": False, "cases": results, "bfcachePixels": lifecycle_pixels(lifecycle)}
(output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
print(f"Synthetic transport/analyzer fixtures retained (NOT browser results): {output}")
