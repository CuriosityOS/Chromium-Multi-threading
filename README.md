# Chromium Multi-threading: style, layout and paint off the main thread

An experimental patch to **Chromium 153.0.8010.55** (Linux) that moves each page's CSS style, layout, paint and raster onto its own
**render thread**, following the model Andreas Kling describes for Ladybird:

* the **main thread** runs JavaScript and keeps a *journal* of DOM / CSSOM mutations;
* each **page** gets its own **render thread** (`BlinkRenderThread`, a `WorkerBackingThread` with its own V8 isolate and Oilpan heap). It
  keeps a **replica** of the page's document, replays the journal onto it, and runs style → layout → paint → raster → frame submission
  on its own schedule;
* synchronous layout queries from script (`offsetHeight`, `getBoundingClientRect()`, `getComputedStyle()`, `elementFromPoint()`, …)
  **block the main thread and ask that page's render thread**, which brings the replica up to date and answers.

The result: a CSS `height` / `grid-template-rows` transition keeps laying out and painting new frames **while JavaScript busy-loops
on the main thread**, and script inside that loop reads the *live* geometry.

![stock vs off-main-thread during a 3 s JS busy loop](media/side-by-side.gif)

*Left: stock Chromium, same binary with the feature off. The layout animation freezes for the whole 3 s synchronous loop.
Right: `--enable-blink-features=OffMainThreadRendering`. The cyan panel keeps growing, the yellow normal-flow sibling moves with it,
and new frames come from the page's render thread. Taken from the lossless X11 capture of validation run `approved-20260926T180001Z`.*

It is **not** a V8-interrupt trick and **not** a compositor-only animation. Height and grid-template-rows cannot be composited; every
frame here is a real style + layout + paint pass, on another thread.

## Results (release validation run `approved-20260926T183827Z`: **PASS**)

The harness drives Chromium through CDP. Pixels are recorded independently from the X server as lossless FFV1 with absolute
timestamps, and each result is also checked against the Chrome trace. Details are in [`validation/README.md`](validation/README.md).

| Case (same binary, flag off vs on) | stock: layout changes during block | OMT: layout changes during block | OMT height range |
|---|---:|---:|---:|
| height transition, 3 s block | 0 | 66 | 218 px |
| grid-template-rows, 3 s block | 0 | 66 | 218 px |
| sync queries + both transitions, 3 s block | 0 | 66 | 217 px |
| height transition, 10 s block | 0 | 233 | 233 px |
| grid-template-rows, 10 s block | 0 | 233 | 233 px |
| sync queries + both transitions, 10 s block | 0 | 234 | 234 px |

The capture is 30 samples/s, so these are captured layout steps, not an FPS claim.

Every case passes all of these gates:

* **Trace attribution.** For each page, `ReplicaPage::BeginFrame` and `ReplicaPage::Paint` run on that page's own `BlinkRenderThread`
  (a distinct TID in the same renderer process) throughout the block, while `CrRendererMain` is inside one long task.
* **No main-thread rendering.** Every entry into `Document::UpdateStyleAndLayoutTree` / `UpdateStyleAndLayout` on a journaled
  document emits `RenderThreadJournal::MainThreadFallback`. The count is **0 during every block**. The only exception is one
  entry before a 10 s block, which is outside the measured window.
* **Synchronous queries are answered by the render thread.** Inside the busy loop, `offsetHeight`, `getBoundingClientRect().height`
  and `getComputedStyle().height` grow 24 → 264 px along the transition. Also inside the block:
  * 68 exact DOM/CSSOM/geometry assertions: create, insert and remove, inline style, CSSOM insertRule/deleteRule, custom properties,
    `::before`, scroll offsets, window scroll, `innerWidth`/`innerHeight`, Range rects, innerText, light/shadow hit testing, and
    focusability.
  * All 68 give the same values as stock Chromium.
  * Each `RenderThread::RunQuery` on main encloses exactly one matching `ReplicaPage::AnswerQuery` on the render thread (sub-ms to ~3 ms).
* **Native input.** An xdotool XTEST click is hit-tested by the render thread (queries HitTest and MouseRelativePosition). It gives
  the same target, `offsetX/Y` and focus as stock.
* **One render thread per page.** `window.open` to a same-process peer gives 1 → 2 → 1 threads. Navigation a→b and
  `history.back()` from the back/forward cache both keep it at 1. The BFCache restore starts a *fresh* render thread and replica.
  That restore is checked through geometry, preserved DOM, and new X11 pixels (64 → 24 → 64 → 96 px).
* Resize, navigation, DOM/CSSOM smoke tests, and no crash or fatal log signatures.

## How it works

```
 main thread (CrRendererMain)                          render thread (BlinkRenderThread), one per page
 ─────────────────────────────                          ───────────────────────────────────────────────
 JS mutates DOM / CSSOM ──► RenderThreadJournal          ReplicaPage (own isolate + Oilpan heap)
   (node ids, ops: create/insert/remove/attr/text/        ├─ applies committed ops (and uncommitted ones
    inline style/sheet text/state/scroll/viewport)        │   after ~20 ms, so long tasks still progress)
        │   committed at end of each task                 ├─ style → layout → pre-paint → paint
        └──────────► RenderThreadChannel (lock) ─────────►├─ raster (Canvas2DResourceProvider)
                                                          └─ CanvasResourceDispatcher → viz surface
 JS reads layout ──► RenderThread::RunQuery ──(blocks)──► ReplicaPage::AnswerQuery (brings replica up to date)
 main frame: SurfaceLayer (foreign layer) that embeds the render thread's surface; main never paints the page
```

Key pieces (new code in [`overlay/third_party/blink/renderer/core/render_thread/`](overlay/third_party/blink/renderer/core/render_thread)):

* `render_thread_journal.{h,cc}`: main-thread side.
  * Assigns node ids and serializes DOM/CSSOM changes. `<link>` sheets are sent as sheet text, and scripts, media and iframes are
    stripped.
  * Owns the page's `RenderThread` and exposes the static `Query*`, `HitTest` and `Scroll` entry points used by Blink's bindings.
  * Stops the render thread when the page enters the BFCache and starts a new one on restore.
* `render_thread.{h,cc}`: `RenderThread` wraps one `WorkerBackingThread` per page.
  * `ReplicaPage` is a non-ordinary `Page`/`LocalFrame`/`Document` with scripting off that runs the lifecycle and produces frames.
  * `RunQuery` waits on the answer while servicing only render-thread→main GPU/font hops, never arbitrary main tasks. This means no
    re-entrant JS and no deadlock.
* `render_thread_channel.{h,cc}`: the op/query protocol and the locked queue.

Making Blink run a second document lifecycle concurrently on another thread required:

* **Thread-safety work** in ~100 files, mostly converting process-wide mutable statics to per-thread ones
  (`platform/wtf/per_thread_static.h`, `constinit thread_local`) or to atomics. Examples:
  * `QualifiedName` refcount and cache.
  * DOMNodeIds and WeakIdentifierMap ids.
  * Scope counters (event dispatch, script forbidden, post style update, display lock memoizer, paint timing, …).
  * Caches such as computed-style property lists, wavy decoration, and slot LCS tables.

  See the [audit reports](audit/).
* **Oilpan affinity:** `kMainThreadOnly` types allocate on the *current* thread's heap (`thread_state_storage.h`).
* **Main-thread checks** relaxed to `IsMainOrBlinkRenderThread()` where the replica legitimately runs the code.
* **Hooks** where main would otherwise run style/layout:
  * Element/HTMLElement/TreeScope/CSSComputedStyleDeclaration/Range/MouseEvent/LocalDOMWindow getters route to the render thread.
  * The scroll setters and `scrollTo`/`scrollBy` are journaled.
  * `Document::PerformMouseEventHitTest` and `HitTestResultInFrame` ask the render thread.
  * Focusability is a render-thread query.
  * `LocalFrameView::UpdateLifecyclePhases` (BeginMainFrame) hands the frame to the presenter instead of painting.

## Repository layout

| Path | What |
|---|---|
| [`patches/chromium-153.0.8010.55-omt.patch`](patches/) | The complete change: `git diff` against tag `153.0.8010.55`, including new files. |
| `overlay/` | New source files, as they are in the tree. |
| `edits/` | The individual exact-replacement edit specs, in the order they were applied (history of the work). |
| `redit.py`, `push.sh`, `errs.sh` | Tooling used to apply edits / sync the overlay to the build machine / show build errors. |
| `validation/` | CDP + X11-capture validation harness, demo pages, analyzer, tests, and the per-run reports (`validation/results/*/REPORT.md`). |
| `audit/` | Thread-safety audit reports. |
| `smoke/` | Small manual test pages. |
| `media/` | The side-by-side capture above (mp4 + gif). |

## Build and run

```sh
# Chromium checkout at tag 153.0.8010.55 (Linux)
cd src && git apply /path/to/patches/chromium-153.0.8010.55-omt.patch
gn gen out/Omt --args='is_debug=false is_component_build=true symbol_level=1 dcheck_always_on=false'
autoninja -C out/Omt chrome
out/Omt/chrome --enable-blink-features=OffMainThreadRendering https://example.com/
```

Logs with `--enable-logging=stderr --v=0` show `[OMT] …` lines: render thread start, replica creation, first frame, first query
answer, and every main-thread fallback. Validation: `cd validation && bash run.sh --build-ready` (see its README).
