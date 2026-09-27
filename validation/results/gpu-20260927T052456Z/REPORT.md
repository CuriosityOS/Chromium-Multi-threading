# OMT validation

**FAIL**

| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | TakeOver after start | HandBack after end | Result |
|---|---|---:|---:|---:|---|---:|---:|---|
| baseline | height | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | grid | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | queries | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | height | 10000ms | 0 | 0px | — | — | — | PASS |
| baseline | grid | 10000ms | 0 | 0px | — | — | — | PASS |
| baseline | queries | 10000ms | 0 | 0px | — | — | — | PASS |
| omt | height | 3000ms | 135 | 225px | 3228895/3229218 | 64.3ms | 43.7ms | PASS |
| omt | grid | 3000ms | 135 | 225px | 3228895/3229302 | 64.3ms | 46.6ms | PASS |
| omt | queries | 3000ms | 136 | 227px | 3228895/3229391 | 64.3ms | 34.8ms | PASS |
| omt | height | 10000ms | 235 | 235px | 3228895/3229512 | 64.3ms | 27.5ms | PASS |
| omt | grid | 10000ms | 235 | 235px | 3228895/3229666 | 64.2ms | 46.9ms | PASS |
| omt | queries | 10000ms | — | —px | — | — | — | FAIL |

## Main-thread lifecycle entries (conservative unthrottled fallback counts)

SkippedForFocus is informational: skipped work is counted separately, never subtracted from fallbacks.

| Mode/case | Before block | During block | After block | SkippedForFocus before/during/after |
|---|---:|---:|---:|---|
| baseline/height/3000 | 0 | 0 | 0 | 0/0/0 |
| baseline/grid/3000 | 0 | 0 | 0 | 0/0/0 |
| baseline/queries/3000 | 0 | 0 | 0 | 0/0/0 |
| baseline/height/10000 | 0 | 0 | 0 | 0/0/0 |
| baseline/grid/10000 | 0 | 0 | 0 | 0/0/0 |
| baseline/queries/10000 | 0 | 0 | 0 | 0/0/0 |
| omt/height/3000 | 0 | 0 | 0 | 0/0/0 |
| omt/grid/3000 | 0 | 0 | 0 | 0/0/0 |
| omt/queries/3000 | 0 | 0 | 0 | 0/10/0 |
| omt/height/10000 | 0 | 0 | 0 | 0/0/0 |
| omt/grid/10000 | 0 | 0 | 0 | 0/0/0 |

## BFCache restoration

| Mode | Render thread counts | pageshow.persisted | X11 heights A/B/restored/fresh | Fresh replica | Fresh Paints |
|---|---|---|---|---|---|
| baseline | 0 → 0 → 0 → 0 → 0 | True | 64/24/64/96px | none | n/a |
| omt | FAIL / incomplete | — | — | — | — |

## Memory (medians)

| Mode | Renderer churn 5–10s | Renderer churn last 5s | Renderer idle last 10s | TakeOvers during churn | GPU process PSS churn/idle | GPU process VRAM churn/idle |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 133.5MB | 134.3MB | 72.5MB | 0 | 153.7MB / 152.8MB | 50.0MiB / 45.0MiB |
| omt | FAIL / incomplete | — | — | — | — | — |

## Display / capture

- Capture: display :20, 60 fps requested
- nvidia-smi: NVIDIA GeForce RTX 4090, 595.84, 1138 MiB, 23028 MiB
- DPMS: before {'enabled': True, 'monitor': 'Off'}, during {'enabled': True, 'monitor': 'On'}, after {'enabled': True, 'monitor': 'Off'}, restored=True
- baseline: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {}, window origin {'x': 0, 'y': 52}
- omt: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {'gpu': 6}, window origin {'x': 0, 'y': 52}

## Failures
- omt/queries-10000: {"method":"Inspector.targetCrashed","params":{}}
- omt: Error: {"method":"Inspector.targetCrashed","params":{}}
    at WebSocket.<anonymous> (file:///root/cr153/validation/cdp.mjs:33:21)
    at [nodejs.internal.kHybridDispatch] (node:internal/event_target:843:20)
    at WebSocket.dispatchEvent (node:internal/event_target:776:26)
    at fireEvent (node:internal/deps/undici/undici:13189:14)
    at #onMessage (node:internal/deps/undici/undici:14418:9)
    at Object.onMessage (node:internal/deps/undici/undici:14131:76)
    at websocketMessageReceived (node:internal/deps/undici/undici:13193:15)
    at node:internal/deps/undici/undici:13850:19
    at node:internal/deps/undici/undici:13670:11
    at afterWrite (node:internal/streams/writable:710:5)
- omt: fatal Chromium log signatures
- omt: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/smoke.json'
- omt/native-input: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/input/input.json'
- omt/page-threads: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/page-threads/threads.json'
- omt/smoke-trace: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/smoke-trace/trace-complete.json'
- omt/memory: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/mem/memory.json'
- omt/unreplicable: [Errno 2] No such file or directory: '/root/cr153/validation/results/gpu-20260927T052456Z/omt/unreplicable/unreplicable.json'
- baseline comparison: 'block'
- memory comparison: memory evidence missing for a mode
- queries/10000: missing OMT-versus-baseline differential
- omt/queries/10000: Harness milestones incomplete
- omt/queries/10000: pixels: Command failed ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', '/root/cr153/validation/results/gpu-20260927T052456Z/omt/queries-10000/capture.mkv']: /root/cr153/validation/results/gpu-20260927T052456Z/omt/queries-10000/capture.mkv: No such file or directory

- omt/queries/10000: trace: Trace milestone missing/ambiguous: mutation
- omt/queries/10000: fallbacks: Missing/ambiguous trace marker block-start
- omt/queries/10000: handoff: Missing/ambiguous trace marker block-start
- omt/queries/10000: queries: 'block'

## Interpretation

Real X display :20 (GPU, compositing window manager), 60 fps x11grab of the harness window; not physical scanout timing or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
