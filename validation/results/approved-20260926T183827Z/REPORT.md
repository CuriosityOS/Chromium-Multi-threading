# OMT validation

**PASS**

| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | Result |
|---|---|---:|---:|---:|---|---|
| baseline | height | 3000ms | 0 | 0px | — | PASS |
| baseline | grid | 3000ms | 0 | 0px | — | PASS |
| baseline | queries | 3000ms | 0 | 0px | — | PASS |
| baseline | height | 10000ms | 0 | 0px | — | PASS |
| baseline | grid | 10000ms | 0 | 0px | — | PASS |
| baseline | queries | 10000ms | 0 | 0px | — | PASS |
| omt | height | 3000ms | 66 | 218px | 2892435/2892858 | PASS |
| omt | grid | 3000ms | 66 | 218px | 2892435/2892978 | PASS |
| omt | queries | 3000ms | 66 | 217px | 2892435/2893063 | PASS |
| omt | height | 10000ms | 233 | 233px | 2892435/2893230 | PASS |
| omt | grid | 10000ms | 233 | 233px | 2892435/2893430 | PASS |
| omt | queries | 10000ms | 234 | 234px | 2892435/2893611 | PASS |

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
| omt | 1 → 2 → 1 → 1 → 1 | True | 64/24/64/96px | 6 | 10 |

## Failures

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.

## Release provenance

All four manifests match across803 files. SHA256:
`9a63ea1594e8960360c463a939871a34d57635977a3be772f1b2c56edc4c3877`

## Run context (post-run note)

The parent reports a separately launched28-job `blink_unittests` run overlapped validation startup and the three baseline3s capture windows through **18:39:33 UTC**. Recorded baseline3s blocks were18:39:03.556–06.556,18:39:17.923–20.923 and18:39:26.571–29.571. All passed the unchanged timing, pixel and trace gates.

Baseline10s measured blocks start at18:39:35.255; OMT measurements begin at18:41:19.303, after the reported overlap. No gates or thresholds changed. This is functional software-display validation, not an unloaded baseline-versus-OMT performance benchmark. See RUN-NOTES.md for the original parent-reported context.
