# OMT validation

**PASS**

| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | TakeOver after start | HandBack after end | Result |
|---|---|---:|---:|---:|---|---:|---:|---|
| baseline | height | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | grid | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | queries | 3000ms | 0 | 0px | — | — | — | PASS |
| baseline | height | 10000ms | 0 | 0px | — | — | — | PASS |
| baseline | grid | 10000ms | 0 | 0px | — | — | — | PASS |
| baseline | queries | 10000ms | 0 | 0px | — | — | — | PASS |
| omt | height | 3000ms | 135 | 225px | 3286638/3286941 | 64.3ms | 47.1ms | PASS |
| omt | grid | 3000ms | 135 | 225px | 3286638/3287053 | 64.3ms | 30.6ms | PASS |
| omt | queries | 3000ms | 136 | 226px | 3286638/3287155 | 64.3ms | 38.5ms | PASS |
| omt | height | 10000ms | 235 | 235px | 3286638/3287221 | 64.3ms | 45.7ms | PASS |
| omt | grid | 10000ms | 235 | 235px | 3286638/3287401 | 64.3ms | 46.2ms | PASS |
| omt | queries | 10000ms | 236 | 236px | 3286638/3287560 | 64.2ms | 35.0ms | PASS |

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
| omt/queries/10000 | 0 | 0 | 0 | 0/10/0 |

## BFCache restoration

| Mode | Render thread counts | pageshow.persisted | X11 heights A/B/restored/fresh | Fresh replica | Fresh Paints |
|---|---|---|---|---|---|
| baseline | 0 → 0 → 0 → 0 → 0 | True | 64/24/64/96px | none | n/a |
| omt | 1 → 2 → 1 → 1 → 1 | True | 64/24/64/96px | 6 | 1 |

## Memory (medians)

| Mode | Renderer churn 5–10s | Renderer churn last 5s | Renderer idle last 10s | TakeOvers during churn | GPU process PSS churn/idle | GPU process VRAM churn/idle |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 131.6MB | 132.5MB | 71.2MB | 0 | 155.4MB / 156.7MB | 50.0MiB / 45.0MiB |
| omt | 214.8MB | 215.9MB | 92.3MB | 0 | 157.1MB / 157.6MB | 56.0MiB / 51.0MiB |

## Display / capture

- Capture: display :20, 60 fps requested
- nvidia-smi: NVIDIA GeForce RTX 4090, 595.84, 1120 MiB, 23028 MiB
- DPMS: before {'enabled': True, 'monitor': 'Off'}, during {'enabled': True, 'monitor': 'On'}, after {'enabled': True, 'monitor': 'Off'}, restored=True
- baseline: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {}, window origin {'x': 0, 'y': 52}
- omt: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {'gpu': 17}, window origin {'x': 0, 'y': 52}

## Failures

## Interpretation

Real X display :20 (GPU, compositing window manager), 60 fps x11grab of the harness window; not physical scanout timing or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
