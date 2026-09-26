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
| omt | height | 3000ms | 66 | 218px | 2491512/2491870 | PASS |
| omt | grid | 3000ms | 66 | 218px | 2491512/2492016 | PASS |
| omt | queries | 3000ms | 66 | 219px | 2491512/2492071 | PASS |
| omt | height | 10000ms | 233 | 233px | 2491512/2492163 | PASS |
| omt | grid | 10000ms | 233 | 233px | 2491512/2492348 | PASS |
| omt | queries | 10000ms | 234 | 234px | 2491512/2492582 | PASS |

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
| baseline | FAIL / incomplete | — | — | — | — |
| omt | FAIL / incomplete | — | — | — | — |

## Failures
- baseline/smoke: AssertionError [ERR_ASSERTION]: Missing resize event milestone
    at smoke (file:///root/cr153/validation/run.mjs:180:3)
    at async file:///root/cr153/validation/run.mjs:346:15
- baseline/native-input: Error: Missing readiness milestone / timeout
    at waitFor (file:///root/cr153/validation/run.mjs:69:9)
    at async nativeInput (file:///root/cr153/validation/extended.mjs:89:21)
    at async file:///root/cr153/validation/run.mjs:346:15
- baseline/page-threads: AssertionError [ERR_ASSERTION]: History navigation missed BFCache; restore path unproven

false !== true

    at pageThreads (file:///root/cr153/validation/extended.mjs:222:12)
    at async file:///root/cr153/validation/run.mjs:346:15
- omt/page-threads: AssertionError [ERR_ASSERTION]: History navigation missed BFCache; restore path unproven

false !== true

    at pageThreads (file:///root/cr153/validation/extended.mjs:222:12)
    at async file:///root/cr153/validation/run.mjs:346:15
- baseline: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T172500Z/baseline/lifecycle.json'
- baseline/native-input: Input milestones incomplete
- baseline/page-threads: Page-thread lifecycle milestones incomplete
- omt/page-threads: Page-thread lifecycle milestones incomplete
- baseline comparison: Input comparison missing events

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
