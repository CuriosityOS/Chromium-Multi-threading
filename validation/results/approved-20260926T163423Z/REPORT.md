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
| omt | height | 3000ms | 66 | 218px | 2456358/2456758 | PASS |
| omt | grid | 3000ms | 66 | 218px | 2456358/2456854 | PASS |
| omt | queries | 3000ms | 66 | 219px | 2456358/2456993 | PASS |
| omt | height | 10000ms | 233 | 233px | 2456358/2457061 | PASS |
| omt | grid | 10000ms | 233 | 233px | 2456358/2457315 | PASS |
| omt | queries | 10000ms | 234 | 234px | 2456358/2457462 | PASS |

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

## Failures
- omt/native-input: AssertionError [ERR_ASSERTION]: xdotool mousemove --sync 786 785 mousedown 1 sleep 0.05 mouseup 1: 

null !== 0

    at xdo (file:///root/cr153/validation/extended.mjs:39:12)
    at nativeInput (file:///root/cr153/validation/extended.mjs:62:5)
    at async file:///root/cr153/validation/run.mjs:346:15
- omt/page-threads: Error: Missing readiness milestone / timeout
    at waitFor (file:///root/cr153/validation/run.mjs:69:9)
    at async stage (file:///root/cr153/validation/extended.mjs:105:22)
    at async pageThreads (file:///root/cr153/validation/extended.mjs:125:19)
    at async file:///root/cr153/validation/run.mjs:346:15
- omt: fatal Chromium log signatures
- omt: Fatal Chromium log signatures
- omt/native-input: Input milestones incomplete
- omt/page-threads: Page-thread lifecycle milestones incomplete
- baseline comparison: 'events'

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
