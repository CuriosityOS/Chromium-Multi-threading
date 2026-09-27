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
| omt | height | 3000ms | 67 | 222px | 3273986/3274314 | 64.3ms | 38.6ms | PASS |
| omt | grid | 3000ms | 67 | 222px | 3273986/3274443 | 64.3ms | 23.4ms | PASS |
| omt | queries | 3000ms | 68 | 224px | 3273986/3274501 | 64.2ms | 26.4ms | PASS |
| omt | height | 10000ms | 234 | 234px | 3273986/3274609 | 64.2ms | 39.4ms | PASS |
| omt | grid | 10000ms | 234 | 234px | 3273986/3274777 | 64.2ms | 37.9ms | PASS |
| omt | queries | 10000ms | 235 | 235px | 3273986/3275084 | 64.3ms | 27.8ms | PASS |

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
| baseline | 121.5MB | 141.2MB | 62.4MB | 0 | 70.3MB / 71.9MB | — / — |
| omt | 202.9MB | 223.5MB | 104.0MB | 0 | 74.3MB / 99.4MB | — / — |

## Display / capture

- Capture: xvfb :1, 30 fps requested

## Failures

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
