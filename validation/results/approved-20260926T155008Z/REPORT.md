# OMT validation

**FAIL**

| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | Result |
|---|---|---:|---:|---:|---|---|
| baseline | height | 3000ms | — | —px | — | FAIL |
| baseline | grid | 3000ms | 0 | 0px | — | PASS |
| baseline | queries | 3000ms | 0 | 0px | — | PASS |
| baseline | height | 10000ms | 0 | 0px | — | PASS |
| baseline | grid | 10000ms | 0 | 0px | — | PASS |
| baseline | queries | 10000ms | 0 | 0px | — | PASS |
| omt | height | 3000ms | — | —px | — | FAIL |

## Main-thread lifecycle entries (conservative unthrottled fallback counts)

| Mode/case | Before block | During block | After block |
|---|---:|---:|---:|
| baseline/grid/3000 | 0 | 0 | 0 |
| baseline/queries/3000 | 0 | 0 | 0 |
| baseline/height/10000 | 0 | 0 | 0 |
| baseline/grid/10000 | 0 | 0 | 0 |
| baseline/queries/10000 | 0 | 0 | 0 |

## Failures
- baseline/height-3000: CDP timeout: Page.navigate
- omt/height-3000: {"method":"Inspector.targetCrashed","params":{}}
- omt: Error: {"method":"Inspector.targetCrashed","params":{}}
    at WebSocket.<anonymous> (file:///root/cr153/validation/cdp.mjs:30:21)
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
- Missing/duplicate required cases: need baseline + omt, ('height', 'grid', 'queries'), 3s + 10s
- omt: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155008Z/omt/smoke.json'
- omt/native-input: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155008Z/omt/input/input.json'
- omt/page-threads: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155008Z/omt/page-threads/threads.json'
- baseline comparison: Missing paired synchronous-query cases
- height/3000: missing OMT-versus-baseline differential
- height/10000: missing OMT-versus-baseline differential
- grid/3000: missing OMT-versus-baseline differential
- grid/10000: missing OMT-versus-baseline differential
- queries/3000: missing OMT-versus-baseline differential
- queries/10000: missing OMT-versus-baseline differential
- baseline/height/3000: Harness milestones incomplete
- baseline/height/3000: pixels: Command failed ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', '/root/cr153/validation/results/approved-20260926T155008Z/baseline/height-3000/capture.mkv']: /root/cr153/validation/results/approved-20260926T155008Z/baseline/height-3000/capture.mkv: No such file or directory

- baseline/height/3000: trace: Trace milestone missing/ambiguous: mutation
- baseline/height/3000: fallbacks: Missing/ambiguous trace marker block-start
- omt/height/3000: Harness milestones incomplete
- omt/height/3000: pixels: Final captured panel is not 264px: wrong/stale surface
- omt/height/3000: trace: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155008Z/omt/height-3000/trace-complete.json'
- omt/height/3000: fallbacks: [Errno 2] No such file or directory: '/root/cr153/validation/results/approved-20260926T155008Z/omt/height-3000/trace-complete.json'

## Interpretation

Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness. CDP smoke screenshots are not block evidence.

See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts.
