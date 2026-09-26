# Latest full matrix: recorded proof PASS, overall FAIL

Run: `/root/cr153/validation/results/approved-20260926T163423Z`.
Command: `bash run.sh --build-ready --output <run>` via detached wrapper; exit1.
The parent explicitly approved this build. No Chromium source/build files were changed by validation.

## Recorded cases

| Layout/block | Baseline | OMT | OMT changes | Guarded range | Change span | Render TID |
|---|---|---|---:|---:|---:|---:|
| height/3s | PASS | PASS | 66 | 218px | 2167ms | 2456758 |
| grid/3s | PASS | PASS | 66 | 218px | 2166ms | 2456854 |
| queries/3s | PASS | PASS | 66 | 219px | 2167ms | 2456993 |
| height/10s | PASS | PASS | 233 | 233px | 7733ms | 2457061 |
| grid/10s | PASS | PASS | 233 | 233px | 7733ms | 2457315 |
| queries/10s | PASS | PASS | 234 | 234px | 7766ms | 2457462 |

Main renderer PID/TID2456358; all listed render TIDs belong to that same process and are distinct BlinkRenderThread threads. Each trace contains an enclosing main task for the full requested3s/10s. Render traces have132–469 Paint and133–470 BeginFrame events over2.2–7.8s. This is Xvfb software-display proof, not physical GPU scanout/FPS.

Every baseline ROI had zero changes, zero range and one hash:75 guarded samples per3s case and285 per10s case. Both independently measured query panels passed. OMT initial/final captured heights were24/264px. The10s transition-duration issue seen in the prior build is no longer present.

Every measured block had **zero MainThreadFallback entries**. Each OMT query block separately recorded10 informational SkippedForFocus events. One reason17 fallback before the height/10s block is reported, not failed.

## Synchronous-query correctness

Both query durations passed all68 immediate assertions, and the complete assertion objects exactly matched baseline. These include inline CSSOM, custom/pseudo properties, element scrolling, window dimensions/scrolling, Element/Range geometry, rendered text, shadow/document hits and focusability.

- 3s:16 samples,155 paired main/render queries, max wait2848µs.
- 10s:51 samples,365 paired queries, max wait2945µs.
- Every required query family0–27 appeared (native-only19/21 are checked separately).
- Both panels' offset/rect/computed heights progressed24→264 inside the same task.
- Window scrolling restored at9.667ms/5.497ms by same-main-thread trace, safely before the unchanged250ms pixel guard; JS timestamps were9.6ms/5.4ms.

The OMT DOM/CSSOM smoke, resize and navigation-return operations completed their runtime assertions before later mode-health failures. No clean overall health/lifetime claim is made.

## Real Chromium crash

`omt/chrome.log:148`, during deferred replica teardown after navigation:

```
Received signal 11 ... SEGV_ACCERR
#0 base::debug::CollectStackTrace
#1 base::debug::StackTrace::StackTrace
#2 StackDumpSignalHandler
#3 libc.so.6+0x45caf
#4 blink::WeakIdentifierMap<>::Identifier (wtf/hash_table.h:1027)
#5 MainThreadDebugger::DidClearContextsForFrame (main_thread_debugger.cc:208)
#6 LocalDOMWindow::FrameDestroyed (local_dom_window.cc:1144)
#7 LocalFrame::DetachImpl (local_frame.cc:772)
#8 Frame::Detach (frame.cc:125)
#9 Page::WillBeDestroyed (page.cc:1374)
#10 ReplicaPage::~ReplicaPage (render_thread.cc:294)
#11 ShutdownRenderThread (render_thread.cc:912)
#12 base::internal::Invoker<>::RunOnce
#13 base::TaskAnnotator::RunTaskImpl
#14 ThreadControllerWithMessagePumpImpl::DoWorkImpl
```

Two signal headers interleaved; the full raw log is retained. The stack continues through NonMainThreadImpl::SimpleThreadImpl::Run, identifying render-thread teardown. The first15 frames were sent to the parent immediately. The newly navigated renderer2457735 continued running, but the fatal signature correctly fails overall validation.

## Native-input harness failure (not a browser input pass)

Baseline native input passed with trusted mousedown/up/click, targetinput-button, offsets20/15 and focus. OMT's combined xdotool chain timed out before events were retained:

```
mousemove --sync 786 785 mousedown 1 sleep 0.05 mouseup 1
status=null (10s subprocess deadline)
```

A browser-free reproduction with the real harness's `Xvfb -noreset` established an installedxdotool3.20160805.1 bug: first motion succeeds; an identical --sync motion hangs while explicit readback confirms the pointer is already786,785. Plain motion + readback and press/release succeed. An initial experiment without-noreset was misleading because the X server reset/recentered the pointer between clients; that initial interpretation was explicitly corrected.

Reproduction: `preflight/pointer-noreset-20260926T165008Z/result.json`. The next harness revision replaces wait-for-any-movement with explicit destination readback and separately logged press/release. It does not relax trusted-event, target, offset, focus or query-forwarding gates. Native input remains unvalidated for OMT in this run.

Its recorded trace has three **outside-block** fallback entries: layout reason28 twice and13 once. Text logs span a broader preparation window and are also retained. These are reported, not failed. See `omt/input/outside-fallbacks-diagnostic.json`.

## Page lifetime failure

After navigating to owner-a, expected one render thread; observed three in renderer2457735 throughout385 snapshots over20s:

- TID2457753: replica1, navigation-return document.
- TID2457761: replica2, input document.
- TID2457956: replica3, owner-a document.

The test stopped before opening the peer. No per-page/lifetime pass is claimed; BFCache was not disabled and GC was not forced to hide retained threads. The page-lifetime trace has four outside-block fallbacks (28×2,17×1,13×1), reported separately in `omt/page-threads/outside-fallbacks-diagnostic.json`.

## Reproducibility and cleanup

All four runtime manifests matched across791 files:

`66eafe4ebc5b0d5c5efacead020c2b534e9d88342e807c21eb5e0ea96fffa57a`

- chrome: `d4b3ddeab1f58f3beb6a78ce017018dc6d77b378ae9b5678595eb3ed5ea4f910`
- libblink_core.so: `80641fcafdd77c011ca03777b846c686bb285c74f670cb5669cda478cdf316b8`
- libblink_platform.so: `7e39cae87fe40c97058fc55be89296b9ad8d7a9c04d2330d1b6cdce658998f04`

Approximately1.0GB of evidence is copied locally; remote profiles and all original artifacts remain. Original harness source is archived in this run. No harness-profile processes remained after cleanup.

Post-run harness-only changes passed69 tests (53Python+16Node), formatting/lint/syntax/ShellCheck locally/remotely, and the browser-free repeated-position XTEST +68-frame timestamped capture test at `preflight/capture-1790441503375`. These tests are not substituted for an OMT native-input rerun. No additional Chromium launch is planned until the parent approves the next build.
