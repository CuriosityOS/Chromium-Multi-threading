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
| omt | height | 3000ms | 66 | 218px | 2428048/2428450 | PASS |
| omt | grid | 3000ms | 66 | 218px | 2428048/2428847 | PASS |
| omt | queries | 3000ms | — | —px | — | FAIL |
| omt | height | 10000ms | 66 | 218px | 2428048/2429032 | PASS |
| omt | grid | 10000ms | 66 | 218px | 2428048/2429256 | PASS |
| omt | queries | 10000ms | — | —px | — | FAIL |

## Main-thread lifecycle entries (conservative unthrottled fallback counts)

| Mode/case | Before block | During block | After block |
|---|---:|---:|---:|
| baseline/height/3000 | 0 | 0 | 0 |
| baseline/grid/3000 | 0 | 0 | 0 |
| baseline/queries/3000 | 0 | 0 | 0 |
| baseline/height/10000 | 0 | 0 | 0 |
| baseline/grid/10000 | 0 | 0 | 0 |
| baseline/queries/10000 | 0 | 0 | 0 |
| omt/height/3000 | 1 | 0 | 0 |
| omt/grid/3000 | 1 | 0 | 0 |
| omt/queries/3000 | 1 | 8 | 0 |
| omt/height/10000 | 2 | 0 | 0 |
| omt/grid/10000 | 1 | 0 | 0 |
| omt/queries/10000 | 1 | 8 | 0 |

## Failures
- omt/queries-3000: Immediate synchronous-query assertions failed (see block result)
- omt/queries-10000: Immediate synchronous-query assertions failed (see block result)
- omt: AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:
+ actual - expected

+ 'rgb(40, 50, 60)'
- 'rgb(40, 200, 80)'
           ^

    at smoke (file:///root/cr153/validation/run.mjs:160:14)
    at async file:///root/cr153/validation/run.mjs:339:7
- omt: Smoke milestones incomplete
- omt/native-input: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155925Z/omt/input/input.json'
- omt/page-threads: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155925Z/omt/page-threads/threads.json'
- baseline comparison: Baseline/OMT differ on immediate DOM/CSSOM/shadow/focus results
- queries/3000: missing OMT-versus-baseline differential
- queries/10000: missing OMT-versus-baseline differential
- omt/queries/3000: Harness milestones incomplete
- omt/queries/3000: pixels: OMT: fewer than 5 layout pixel changes during block
- omt/queries/3000: trace: No sustained OMT BeginFrame + Paint events on a non-main renderer thread during busy block
- omt/queries/3000: fallbacks: Main-thread style/layout fallback during block (or fallback timestamp unavailable)
- omt/queries/3000: queries: Immediate query mismatches: ['immediate inline mutation offsetWidth', 'CSSOM custom property', 'scrollLeft', 'scrollTop']
- omt/queries/10000: Harness milestones incomplete
- omt/queries/10000: pixels: OMT: fewer than 5 layout pixel changes during block
- omt/queries/10000: trace: No sustained OMT BeginFrame + Paint events on a non-main renderer thread during busy block
- omt/queries/10000: fallbacks: Main-thread style/layout fallback during block (or fallback timestamp unavailable)
- omt/queries/10000: queries: Immediate query mismatches: ['immediate inline mutation offsetWidth', 'CSSOM custom property', 'scrollLeft', 'scrollTop']

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
