# Chromium Multi-threading: style, layout and paint off the main thread

An experimental patch to **Chromium 153.0.8010.55** (Linux) that gives each page its own **render thread**. That thread can run
CSS style, layout, paint and raster for the page whenever the main thread is stuck in JavaScript. The model follows the one Andreas
Kling describes for Ladybird:

* the **main thread** runs JavaScript and keeps a *journal* of DOM / CSSOM mutations;
* each **page** gets its own **render thread** (`BlinkRenderThread`, a `WorkerBackingThread` with its own V8 isolate and Oilpan heap).
  It keeps a **replica** of the page's document up to date from the journal;
* **hybrid hand-off / hand-back.**
  * While the main thread is responsive, it renders the page with the normal Blink lifecycle. The render thread only follows along:
    it applies the journal and keeps style and animation state in sync, but does no layout or paint.
  * If a single main-thread task runs longer than **50 ms**, the render thread **takes over**: it runs style → layout → paint →
    raster → frame submission on its own schedule.
  * When the task ends, rendering is **handed back**. Main adopts the render thread's animation start times and renders the next
    frame itself.
* while the render thread is rendering, synchronous layout queries from script (`offsetHeight`, `getBoundingClientRect()`,
  `getComputedStyle()`, `elementFromPoint()`, …) **block and ask that page's render thread**, so script sees the geometry that is
  on screen.

The result: a CSS `height` / `grid-template-rows` transition keeps laying out and painting new frames **while JavaScript busy-loops
on the main thread**. Script inside the loop reads the *live* geometry, and once the loop ends the main thread continues the same
animation without a jump.

![stock vs off-main-thread during a 3 s JS busy loop](media/side-by-side.gif)

*Left: stock Chromium, same binary with the feature off. The layout animation freezes for the whole 3 s synchronous loop.
Right: `--enable-blink-features=OffMainThreadRendering`. About 64 ms into the loop the render thread takes over. The cyan panel keeps
growing, the yellow normal-flow sibling moves with it, and afterwards the main thread takes rendering back. Taken from the lossless
X11 capture of validation run `hybrid-20260927T035246Z`.*

It is **not** a V8-interrupt trick and **not** a compositor-only animation. Height and grid-template-rows cannot be composited; every
frame during the block is a real style + layout + paint pass, on another thread.

## Results (validation run `hybrid-20260927T035246Z`: **PASS**, binary sha256 `f0693ef1…3e74be6`)

The harness drives Chromium through CDP. Pixels are recorded independently from the X server as lossless FFV1 with absolute
timestamps, and each result is also checked against the Chrome trace. Details are in [`validation/README.md`](validation/README.md).

| Case (same binary, flag off vs on) | stock: layout steps during block | OMT: layout steps during block | OMT height range | TakeOver after block start | HandBack after block end |
|---|---:|---:|---:|---:|---:|
| height transition, 3 s block | 0 | 67 | 222 px | 64.3 ms | 38.9 ms |
| grid-template-rows, 3 s block | 0 | 67 | 222 px | 64.3 ms | 38.8 ms |
| sync queries + both transitions, 3 s block | 0 | 68 | 224 px | 64.3 ms | 27.8 ms |
| height transition, 10 s block | 0 | 234 | 234 px | 64.2 ms | 38.8 ms |
| grid-template-rows, 10 s block | 0 | 234 | 234 px | 64.2 ms | 38.4 ms |
| sync queries + both transitions, 10 s block | 0 | 235 | 235 px | 64.3 ms | 24.5 ms |

The capture is 30 samples/s, so these are captured layout steps, not an FPS claim.

Every OMT case passes all of these gates:

* **Hand-off / hand-back.**
  * Each block has exactly one `ReplicaPage::TakeOver`, one `BeginHandBack`/`HandBack` pair on main, and one `StopPresenting`.
  * After `StopPresenting` there is **no** render-thread `Paint`, and main paints the following frames (33–90 per case).
  * The captured panel height never decreases from block start to 264 px, including across the hand-back.
* **Trace attribution.** During the block, `ReplicaPage::BeginFrame`/`Paint` run on that page's own `BlinkRenderThread` (147 paints per
  3 s, 483 per 10 s) while `CrRendererMain` is inside one long task.
* **No main-thread rendering while the render thread owns the page.** `RenderThreadJournal::MainThreadFallback` count is 0.
* **Synchronous queries are answered by the render thread.**
  * Inside the busy loop, `offsetHeight`, `getBoundingClientRect().height` and `getComputedStyle().height` grow along the transition.
    That is 155 (3 s) and 365 (10 s) query round-trips, each `RenderThread::RunQuery` on main enclosing exactly one
    `ReplicaPage::AnswerQuery` on the render thread (max 1.4 / 3.0 ms).
  * 68 exact DOM/CSSOM/geometry assertions give the same values as stock.
* **Native input** (xdotool XTEST click) gives the same target, `offsetX/Y` and focus as stock.
* **One render thread per page.**
  * `window.open` to a same-process peer gives 1 → 2 → 1 threads, and navigation keeps it at 1.
  * A back/forward-cache restore starts a fresh render thread, which takes over a busy block on the restored page.
* **Unreplicable pages** (see limits) log it, never take over, and render normally on main.
* **Memory** (renderer PSS, `demo/mem.html`: 20 s of DOM/style churn in 16 ms tasks, then idle):

  | | churn (median) | idle (median of last 10 s) |
  |---|---:|---:|
  | stock | 143 MB | 81 MB |
  | OMT | 226 MB | 106 MB |

  During churn the replica's DOM and its separate Oilpan/V8 heap cost about 80 MB extra, which is released when the page goes idle.
  Idle overhead is about 25 MB (gate: ≤ 48 MB). There is no growth over time, and 0 takeovers happen during churn because the
  16 ms tasks never reach the 50 ms threshold.
* Resize, navigation and DOM/CSSOM smoke tests pass, with no crash or fatal log signatures.

### v1 → hybrid

The first release rendered *every* frame on the render thread, and main never painted. That had two problems. The main thread
almost never went idle, so its Oilpan heap was never swept (`blink_gc/main` stayed around 100 MB versus about 2 MB in stock). And
there was no way back to normal rendering once main was free again. The hybrid model fixes both: main renders normally and gets its
idle-time GC back, and the render thread only renders while main is actually blocked.

## How it works

```
 main thread (CrRendererMain)                          render thread (BlinkRenderThread), one per page
 ─────────────────────────────                          ───────────────────────────────────────────────
 JS mutates DOM / CSSOM ──► RenderThreadJournal          ReplicaPage (own isolate + Oilpan heap)
   (node ids, ops: create/insert/remove/attr/text/        FOLLOW (main idle): apply committed ops;
    inline style/sheet text/state/scroll/viewport,          style + animation update at main's style-sync
    style-sync markers with main's animation time)          markers (main's animation clock); no layout/paint
        │   committed at end of each task                 TAKEOVER (main task ≥ 50 ms): apply all ops,
        └──────────► RenderThreadChannel (lock) ─────────►  style → layout → paint → raster → viz surface
 main renders normally (stock lifecycle) when idle        HAND-BACK: answer AnimationTimings, stop presenting,
 JS reads layout during takeover ──► RunQuery ──(blocks)──► submit a transparent frame
 after the task: replay scrolls, adopt R's animation start times, render, then R stops presenting
 main frame paints R's SurfaceLayer as a topmost, hit-test-transparent foreign layer (transparent unless R is presenting)
```

Key pieces (new code in [`overlay/third_party/blink/renderer/core/render_thread/`](overlay/third_party/blink/renderer/core/render_thread)):

* `render_thread_journal.{h,cc}`: main-thread side.
  * Assigns node ids and serializes DOM/CSSOM changes. `<link>` sheets are sent as sheet text, and scripts are stripped.
  * Tracks task boundaries, and emits style-sync markers so the replica's animations run on main's clock.
  * Runs the hand-back:
    * replays scrolls made during the takeover;
    * pulls the running animations' start times from the render thread and sets them on main's animations (`setStartTime`);
    * finishes transitions that already ended on the render thread;
    * releases the render thread after main's next frame is presented.
  * Decides whether a page is replicable, and whether takeover is allowed (for example, not while a Web Animation or a non-1
    playback rate is running).
  * Stops the render thread when the page enters the BFCache and starts a new one on restore.
* `render_thread.{h,cc}`: `RenderThread` wraps one `WorkerBackingThread` per page.
  * `ReplicaPage` is a non-ordinary `Page`/`LocalFrame`/`Document` with scripting off. It follows, takes over, produces frames through
    `CanvasResourceDispatcher`, and answers queries.
  * A 16 ms watchdog, armed only while there are uncommitted ops or running animations, detects the long main task.
  * `RunQuery` waits on the answer while servicing only render-thread→main GPU/font hops, never arbitrary main tasks. This means no
    re-entrant JS and no deadlock.
* `render_thread_channel.{h,cc}`: the op/query protocol, the locked queue, and the atomic mode (`kMain` / `kRender` / `kHandBack`) and
  main-task start time.

Making Blink run a second document lifecycle concurrently on another thread required:

* **Thread-safety work** in ~100 files, mostly converting process-wide mutable statics to per-thread ones
  (`platform/wtf/per_thread_static.h`, `constinit thread_local`) or to atomics. Examples:
  * `QualifiedName` refcount and cache.
  * DOMNodeIds and WeakIdentifierMap ids.
  * Scope counters (event dispatch, script forbidden, post style update, display lock memoizer, paint timing, …).
  * Caches such as computed-style property lists, wavy decoration, slot LCS tables, and the selector-statistics map used under
    `blink.debug` tracing.

  See the [audit reports](audit/).
* **Oilpan affinity:** `kMainThreadOnly` types allocate on the *current* thread's heap (`thread_state_storage.h`).
* **Main-thread checks** relaxed to `IsMainOrBlinkRenderThread()` where the replica legitimately runs the code.
* **Hooks.**
  * Element/HTMLElement/TreeScope/CSSComputedStyleDeclaration/Range/MouseEvent/LocalDOMWindow getters, hit testing, focusability
    and the scroll setters route to the render thread *while it is rendering*.
  * `Document::UpdateStyleAndLayoutTree` drives the style-sync and hand-back timing adoption.
  * `LocalFrameView` sends the viewport and scroll offsets after each main frame, and paints the render thread's surface layer.

## Limits (measured, not hidden)

* **Takeover latency.** The first render-thread frame comes about 50–65 ms after a long task starts. Shorter tasks are handled by main
  as in stock.
* **Unreplicable content disables takeover for the page**, which then behaves exactly like stock. This covers `img`, `video`,
  `audio`, `canvas`, iframes, `embed`/`object`, form controls other than buttons/checkboxes/radios, `dialog`, `popover`, SVG
  `image`/`use`/`feImage`, and style sheets with `url(` / `image-set(` / `@font-face`. The replica has no resource loading or
  plugin state.
* **Compositor scrolling freezes during a takeover.** The render thread's surface covers the viewport. Scroll offsets set by script
  during the block are replayed on main at hand-back.
* Composited (transform/opacity) animation start times can drift by 1–2 frames across a hand-back. `:visited` and
  `:focus-visible` styling can differ on the replica.
* **Memory.** Idle cost is about 25 MB per page, and heavy DOM churn costs about 80 MB extra while it lasts (a second heap and
  isolate per page).
* Linux/X11 only. It was validated on Xvfb with software raster, not physical GPU scanout. This is a research prototype, not an
  upstreamable change.

## Repository layout

| Path | What |
|---|---|
| [`patches/chromium-153.0.8010.55-omt.patch`](patches/) | The complete change: `git diff` against tag `153.0.8010.55`, including new files. |
| `overlay/` | New source files, as they are in the tree. |
| `edits/` | The individual exact-replacement edit specs from v1, in the order they were applied (history). The hybrid hooks are only in the patch. |
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

Logs with `--enable-logging=stderr --v=0` show `[OMT] …` lines: render thread start, replica creation, each takeover ("took over
rendering from the busy main thread"), timing adoption, each hand-back, and pages that cannot be replicated. Validation: `cd validation && bash run.sh --build-ready` (see its README).
