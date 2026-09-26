# PASS — complete Linux/Xvfb validation

Approved run: `/root/cr153/validation/results/approved-20260926T180001Z`.
Exit **0**; REPORT.md and analysis.json report **PASS**, with no failures or fatal signatures. All requested gates completed; no exclusions or thresholds were relaxed to obtain this result.

## Independent layout during blocked JavaScript

| Layout/block | Baseline changes/range | OMT changes/range/span | Render TID | BeginFrame/Paint |
|---|---|---|---:|---:|
| height / 3s | 0 / 0px | 66 / 218px / 2166ms | 2520049 | 134 / 133 |
| grid / 3s | 0 / 0px | 66 / 218px / 2167ms | 2520145 | 133 / 132 |
| queries / 3s | 0 / 0px | 66 / 219px / 2167ms | 2520213 | 133 / 132 |
| height / 10s | 0 / 0px | 233 / 233px / 7733ms | 2520293 | 470 / 469 |
| grid / 10s | 0 / 0px | 233 / 233px / 7734ms | 2520520 | 469 / 468 |
| queries / 10s | 0 / 0px | 234 / 234px / 7767ms | 2520701 | 469 / 468 |

Recording main PID/TID: **2519682**, CrRendererMain. Each listed BlinkRenderThread belongs to that same renderer and has a distinct TID. Traces establish enclosing ordinary timer tasks covering the mutations and full 3s/10s blocks. Render BeginFrame/Paint activity spans approximately 2.2s/7.8s inside those blocked tasks.

External lossless X11 capture measures cyan layout height and the yellow normal-flow sibling, not compositor transforms or JS frame counts. Every baseline ROI has one hash and zero layout change. Both independent panels in each query case pass. CDP screenshots are not used as in-block proof.

## Queries, scrolling and fallback accounting

- Both durations pass all **68** immediate DOM/CSSOM, geometry, Range, text, shadow-hit, focusability, element-scroll and window assertions, exactly matching baseline.
- 3s: 155 matched query/answer pairs; maximum wait 3816µs.
- 10s: 365 matched pairs; maximum wait 2027µs.
- All required query families appear with exact same-type trace containment on the distinct render thread.
- Window scroll restoration occurs at 12.968ms / 8.747ms, safely before the unchanged 250ms pixel guard.
- **Zero MainThreadFallback in every measured block.** Each OMT query block has 10 separately counted informational SkippedForFocus entries.
- One reason17 fallback before height/10s is retained and reported, not failed.

The explicitly approved exclusions for computed-style bulk cssText/length remain documented; these are not newly claimed as supported or tested.

## Resize and ordinary lifecycle: PASS

Both modes complete DOM/CSSOM smoke, resize and navigation to about:blank and back.

OMT resize request at epoch1790445864848 produces a handler at4852 reporting the **current 1080×572** viewport; matching readiness completes at4855 (7ms). The restoration handler at4913 correctly reports1279×651. Baseline reports the same current dimensions. Original native bounds are restored and verified. resize.json and resize-samples.jsonl retain measurements.

This resolves the previous run's one-step-behind viewport values without weakening the event/geometry gate.

## Native input: PASS

Both modes produce trusted mousedown → mouseup → click on input-button, offsets20/15 and correct focus. Baseline/OMT event semantics match.

OMT: main PID/TID2520999; render TID2521032; 18 paired queries including HitTest19 and MouseRelativePosition21, maximum595µs. Native XTEST is used, not DOM click or CDP input dispatch.

Outside-block input observations: 5 layout fallbacks (reason28×3,13×1,17×1), plus6 informational focus skips. These are reported separately and do not affect the strict blocked-task gate.

## Per-page ownership and BFCache: PASS

Both modes observe an actual fresh pageshow.persisted=true. Cached console-history replay is retained but excluded from readiness by the milestone's occurrence timestamp.

- Baseline render-thread counts: **0 → 0 → 0 → 0 → 0**.
- OMT counts: **1 → 2 → 1 → 1 → 1**, renderer2520999.
- A: replica3, TID2521104.
- Peer: replica4, TID2521105; closing it preserves A.
- A→B: replica5, TID2521112; A's cached thread stops.
- history.back(): fresh replica6, TID2521138, new journal attachment; B's thread stops.
- Restored A preserves its DOM token and offsetHeight64, then answers96 after a fresh mutation.
- Primary external ROI heights/sibling positions: **64(A) → 24(B) → 64(restored A) → 96(fresh mutation)**. Original/restored64px hashes match;96px differs from both prior surfaces, excluding an old cached bitmap as proof.
- Four paired BoundingClientRect/OffsetHeight queries reach the new thread, maximum897µs. Nine new-thread Paint events follow the fresh mutation.

Outside-block lifetime observations: 12 layout fallbacks (reason28×6,17×3,13×3), no focus skips. All raw evidence remains in analysis.json and the page-threads trace/logs.

## Reproducibility and cleanup

All four runtime manifests match across **791 files**:

`56f0a1616a8a6faed2dd8313d6b3577a49c6f91b5aac82d15ab6addbc56364de`

- chrome: `d4b3ddeab1f58f3beb6a78ce017018dc6d77b378ae9b5678595eb3ed5ea4f910`
- libblink_core.so: `7e6dcf2e33bdc2e6af859bda28728313744b81fbfa356b6baa6e8e9c96ee2268`
- libblink_platform.so: `7e39cae87fe40c97058fc55be89296b9ad8d7a9c04d2330d1b6cdce658998f04`

The same build was used for baseline and enabled modes. The harness source is archived in this run. Approximately **1.0GB** of evidence is retained locally and remotely; profiles remain remote. Exact profile-argument checks found no surviving harness Chromium processes. Harness checks pass83 tests (61Python+22Node), formatting/lint/syntax/ShellCheck.

Scope: this proves the requested behavior on a Linux **Xvfb software display**, not physical GPU scanout/FPS, all web-platform behavior, or cross-platform correctness. No Chromium source/build files were modified by validation.
