# Rebuilt full-matrix result: FAIL

Run: `/root/cr153/validation/results/approved-20260926T155925Z`.
Command: `bash run.sh --build-ready --output <run>` via detached wrapper; exit 1.
No FATAL, target crash, or remaining process with this run's user-data-dir.
All recordings, logs, traces and screenshots are retained remotely and locally; private profiles remain remote.

## Recorded cases

| Layout | Baseline 3s | OMT 3s | Baseline 10s | OMT 10s |
|---|---|---|---|---|
| height | PASS | PASS | PASS | PASS |
| grid | PASS | PASS | PASS | PASS |
| combined queries | PASS | FAIL | PASS | FAIL |

Baseline: 75 guarded samples for each 3s case; 285 for each 10s case. All had zero changes, zero height range, one ROI hash and zero fallback entries.

Passive OMT: each case had 66 captured height changes, 218px guarded height range, 67 ROI hashes, approximately 2167ms change span, and zero in-block fallback entries. Main PID/TID was 2428048. Height3/grid3/height10/grid10 render TIDs were respectively 2428450/2428847/2429032/2429256. Trace counts were 133/132, 133/132, 134/133, 133/132 BeginFrame/Paint pairs, spanning approximately 2200ms. Main-thread enclosing tasks lasted the complete requested 3s/10s.

These are independent changing layout pixels during a blocked main thread, not a claim of animation throughout all ten seconds. The 10s cases also finished their transition near 2.4s rather than the configured 8s; ignored inline custom-property updates are a plausible explanation, not a proven root cause.

## Query failures

Both durations failed the same four of 58 immediate assertions:

| Assertion | Actual | Expected |
|---|---:|---:|
| immediate inline mutation offsetWidth | 137 | 157 |
| CSSOM custom property | 19px | 23px |
| scrollLeft | 0 | 17 |
| scrollTop | 0 | 23 |

All Range geometry assertions passed. Every one of the 16/51 transition samples returned 264px for offset/rect/computed heights of both panels, beginning at approximately 42ms. The primary captured ROI was also frozen at 264px throughout all 75/285 guarded samples, with one hash. An immediate jump is not an animated rendering pass.

Each query block had eight unthrottled fallback trace entries on main: layout reason20 twice, layout13 twice, style0 four times. Reason20 log stacks show:

```
RenderThreadJournal::NoteMainThreadRendering (render_thread_journal.cc:232)
Document::UpdateStyleAndLayout (document.cc:3118)
Document::UpdateStyleAndLayoutForNode (document.cc:2978)
Element::setScrollLeft (element.cc:2743)
v8_element::ScrollLeftAttributeSetCallback
```

The second stack is `Element::setScrollTop (element.cc:2800)`. The other six entries coincide with focus operations. Focus was inside these original measured tasks and is not excused from the no-in-block-fallback gate. Outside-block entries are retained separately in `fallbacks.json`.

Independent diagnostic analysis of the query traces (after correcting the harness's overly broad 100µs matching allowance to exact containment) found 146/356 paired RunQuery/AnswerQuery slices on main2428048 and render2428943/2429458, all required query families, maximum waits1262/2232µs. Pairing does not rescue incorrect values, missing animation or fallbacks. Regression tests cover adjacent same-type queries and an answer extending one microsecond beyond its wait.

## Other checks

Baseline DOM/CSSOM, resize/navigation, native input, and lifecycle passed. Native input produced trusted mousedown/up/click on `input-button`, offsets20,15, and successful focus.

OMT smoke failed at inline mutation:

```
"inlineColor":"rgb(40, 50, 60)","inlineHeight":30
```

Expected color `rgb(40, 200, 80)`, height45. Native-input and page-thread lifetime were not reached in this run; no pass is claimed. Subsequent harness code retains that failure while permitting other fresh-page diagnostic stages to execute if the renderer remains healthy.

## Provenance limitation and follow-up

The executable SHA256 remained `d4b3ddeab1f58f3beb6a78ce017018dc6d77b378ae9b5678595eb3ed5ea4f910` across the parent rebuild because this is a component build. `libblink_core.so` and `libblink_platform.so` had changed. No retrospective DSO fingerprint is claimed for this run. Future runs hash executable, adjacent DSOs/resources, crash handler and locales before each mode and at completion, rejecting differences.

The prior run `approved-20260926T155008Z` is separately retained, including its SyncScrollAttemptHeuristic fatal stack. No Chromium source/build files were changed by validation. Gates were not relaxed. Current harness checks: 46 Python + 12 Node tests pass locally/remotely, plus format/lint/syntax/ShellCheck.
