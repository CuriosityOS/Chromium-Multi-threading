# OMT validation

**FAIL**

| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | Result |
|---|---|---:|---:|---:|---|---|
| baseline | height | 3000ms | 0 | 0px | — | PASS |
| baseline | grid | 3000ms | 0 | 0px | — | PASS |
| baseline | queries | 3000ms | 0 | 0px | — | PASS |
| baseline | height | 10000ms | 0 | 0px | — | PASS |
| baseline | grid | 10000ms | 0 | 0px | — | PASS |
| baseline | queries | 10000ms | 0 | 0px | — | PASS |
| omt | height | 3000ms | 66 | 220px | 2504969/2505419 | PASS |
| omt | grid | 3000ms | 66 | 218px | 2504969/2505558 | PASS |
| omt | queries | 3000ms | 66 | 219px | 2504969/2505596 | PASS |
| omt | height | 10000ms | 233 | 233px | 2504969/2505660 | PASS |
| omt | grid | 10000ms | 233 | 233px | 2504969/2505958 | PASS |
| omt | queries | 10000ms | 234 | 234px | 2504969/2506153 | PASS |

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
| omt/height/10000 | 1 | 0 | 0 | 0/0/0 |
| omt/grid/10000 | 0 | 0 | 0 | 0/0/0 |
| omt/queries/10000 | 0 | 0 | 0 | 0/10/0 |

## BFCache restoration

| Mode | Render thread counts | pageshow.persisted | X11 heights A/B/restored/fresh | Fresh replica | Fresh Paints |
|---|---|---|---|---|---|
| baseline | 0 → 0 → 0 → 0 → 0 | True | 64/24/64/96px | none | n/a |
| omt | 1 → 2 → 1 → 1 → 1 | True | 64/24/64/96px | 12 | 9 |

## Failures
- omt/smoke: Error: Missing readiness milestone / timeout
    at waitFor (file:///root/cr153/validation/run.mjs:70:9)
    at async smoke (file:///root/cr153/validation/run.mjs:179:19)
    at async file:///root/cr153/validation/run.mjs:358:15
- omt: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T174359Z/omt/lifecycle.json'

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
