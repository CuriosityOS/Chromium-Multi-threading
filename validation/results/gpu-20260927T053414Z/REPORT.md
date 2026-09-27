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
| omt | height | 3000ms | 135 | 225px | 3238239/3238544 | 64.3ms | 45.9ms | PASS |
| omt | grid | 3000ms | 135 | 224px | 3238239/3238678 | 64.3ms | 50.5ms | PASS |
| omt | queries | 3000ms | 135 | 225px | 3238239/3238743 | 64.3ms | 18.2ms | PASS |
| omt | height | 10000ms | 235 | 235px | 3238239/3238850 | 64.3ms | 45.9ms | PASS |
| omt | grid | 10000ms | 235 | 235px | 3238239/3239021 | 64.3ms | 47.5ms | PASS |
| omt | queries | 10000ms | 236 | 236px | 3238239/3239182 | 64.3ms | 20.1ms | PASS |

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
| baseline | 138.2MB | 139.2MB | 77.2MB | 0 | 138.1MB / 139.1MB | 50.0MiB / 45.0MiB |
| omt | 216.3MB | 217.2MB | 99.7MB | 0 | 140.5MB / 139.6MB | 54.0MiB / 49.0MiB |

## Display / capture

- Capture: display :20, 60 fps requested
- nvidia-smi: NVIDIA GeForce RTX 4090, 595.84, 1136 MiB, 23028 MiB
- DPMS: before {'enabled': True, 'monitor': 'Off'}, during {'enabled': True, 'monitor': 'On'}, after {'enabled': True, 'monitor': 'Off'}, restored=True
- baseline: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {}, window origin {'x': 0, 'y': 52}
- omt: ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL 4.5.0 NVIDIA 595.84) ((gl=egl-angle,angle=opengl)), features {'gpu_compositing': 'enabled', 'rasterization': 'enabled', 'opengl': 'enabled_on'}, raster providers {'gpu': 17}, window origin {'x': 0, 'y': 52}

## Failures

## Interpretation

Real X display :20 (GPU, compositing window manager), 60 fps x11grab of the harness window; not physical scanout timing or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
