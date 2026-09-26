# Same-build rerun: all rendering/input/BFCache gates PASS; overall FAIL on resize

Run: `/root/cr153/validation/results/approved-20260926T174359Z`; exit1. Parent explicitly approved this same-build rerun. No fatal signatures in either mode. Original source, logs, traces, recordings and screenshots are retained; approximately1GB is copied locally without browser profiles.

## Remaining failure: stale viewport getters in OMT resize handlers

The handler is `addEventListener("resize", () => milestone("resize", {width: innerWidth, height: innerHeight}))` in demo/demo.js:118.

Original native bounds1279×799, viewport1279×651. Browser.setWindowBounds requests1080×720 (expected viewport1080×572).

| Mode/action | Request epochMs | Resize event epochMs | Handler-reported viewport |
|---|---:|---:|---|
| baseline shrink |1790444768156|1790444768158|1080×572, correct|
| baseline restore |after shrink|1790444768228|1279×651, correct|
| OMT shrink |1790444902135|1790444902138|1279×651, old size|
| OMT restore after15s timeout |after timeout|1790444917140|1080×572, previous small size|

The strict readiness gate requires both changed geometry and a fresh resize event whose dimensions match it. OMT times out, then finally restores original bounds and verifies1279×651 geometry. This prevents cross-stage contamination; native-input and BFCache tests subsequently complete successfully. OMT's ordinary navigation-return smoke is unexecuted because the resize assertion stopped that smoke stage, accounting for the missing lifecycle.json secondary failure.

Raw event values are in omt/page-cdp.jsonl and chrome.log, with resize.json holding the request, original bounds, timeout and restored geometry. This run did not retain every geometry poll, so precise replica-update timing cannot be reconstructed from those polls. Future harness versions now retain resize-samples.jsonl and the last sample in resize.json; the gate is unchanged.

The observed one-step-behind event values differ from baseline and CSSOM View's current-viewport getter semantics. Replica viewport publication ordered after resize dispatch/query is a plausible source cause, not yet established by validation. The parent was informed immediately after diagnosis. No main-fallback exemption or timing relaxation was added.

## Twelve recorded cases: PASS

| Layout/block | Baseline changes/range | OMT changes/range/span | Render TID |
|---|---|---|---:|
| height3s |0/0px|66/220px/2166ms|2505419|
| grid3s |0/0px|66/218px/2167ms|2505558|
| queries3s |0/0px|66/219px/2167ms|2505596|
| height10s |0/0px|233/233px/7733ms|2505660|
| grid10s |0/0px|233/233px/7733ms|2505958|
| queries10s |0/0px|234/234px/7767ms|2506153|

Main PID/TID2504969. Each baseline has one guarded ROI hash. Both query ROIs pass. Both durations pass68 immediate assertions exactly equal to baseline;155/365 matched query pairs, max2113/945µs. OMT window scrolling restores at6.673/5.344ms, before the unchanged250ms guard.

Every block has zero MainThreadFallback. Each OMT query block has10 informational SkippedForFocus entries. One reason17 fallback before height/10s remains reported separately, not failed.

## Native input: PASS, including paired baseline comparison

Both modes: trusted mousedown/up/click, correct input-button target, offsets20/15 and focus. Exact baseline/OMT semantics match. OMT has18 matched query pairs including native HitTest19 and MouseRelativePosition21, max612µs; main2504969, render2506519. No stationary-pointer timeout or clipped native window in this run.

## Full BFCache restoration: PASS

Both modes emit an actual fresh pageshow.persisted=true; replayed initial console entries are retained but correctly excluded from readiness.

- Baseline render-thread counts:0→0→0→0→0.
- OMT counts:1→2→1→1→1, all in renderer2504969.
- Owner A: replica9/TID2506643. Peer: replica10/TID2506654. Peer close preserves A.
- A→B: replica11/TID2506678 replaces A; cache-entry and stop logs present.
- history.back(): fresh replica12/TID2506685, fresh A journal attachment; B stops.
- Existing A DOM token persists, restored offsetHeight64 matches original A, then a fresh inline mutation reads96.
- External X11 ROI heights and normal-flow sibling positions:64(A)→24(B)→64(restored A)→96(fresh mutation). Original/restored64px ROI hashes match;96px differs from both previous surfaces, excluding a merely retained cached bitmap.
- Four precisely paired restored BoundingClientRect/OffsetHeight queries reach the new render thread, max421µs. Nine new-thread Paint slices follow the fresh mutation.

See each page-threads directory and analysis.json's extended section. Diagnostic CDP screenshots were taken only after each primary X11 capture.

## Outside-block observations

- OMT native input:5 layout fallbacks (28×3,13×1,17×1),6 informational focus skips.
- OMT lifetime/BFCache:13 layout fallbacks (28×7,17×3,13×3),0 skips.
- Baseline:0 for both stages.

These remain informational outside the strict measured blocks and are not failure causes.

## Identity and cleanup

All four791-file runtime manifests match each other and the previous approved run:
`d683cb43ff6c627da03f819fd38e29fcf7e76a548785598c3b12f571f9db70d9`.

Exact profile-argument checks found no surviving harness Chromium processes. Post-run diagnostic-only changes pass83 tests (61Python+22Node), formatting/lint/syntax/ShellCheck locally/remotely. No further Chromium launch until explicit approval. No Chromium source/build files were changed by validation.
