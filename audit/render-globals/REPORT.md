# Render-thread mutable-global fixes

Applied to `ssh core:/root/cr153/src/third_party/blink/renderer/core/` on 2026-09-26 following the parent’s expanded scope. **32 source files changed in this pass**, in addition to the earlier three QualifiedName files. No builds or git operations were run. The in-progress parent build was not touched.

## Implementation

- Scope pointers/counters are `constinit thread_local`, including matching header declarations, so simultaneous main/render operations are not mistaken for nested operations.
- Oilpan-owning ScopedEventQueue, DCHECK LiveDocumentSet, and AbstractInlineTextBoxCache use the existing `DEFINE_PER_THREAD_STATIC_LOCAL` macro. Existing converted Persistent sites were not redone.
- Document tree-version, DOM node-ID, animation sequence and animation task-clock counters are process-wide atomics with explicit relaxed operations. They allocate scalar counters; they are not object-publication barriers.
- DOMNodeIds performs the max-to-1 wrap and allocation in one CAS loop, rather than racing a separate reset/store against an increment. Existing local-map collision checks are retained.
- HTML attribute-trigger registration is inside a function-local `static const` lambda initializer. Its initialization guard waits for the entire loop to finish, preventing partial publication and duplicate registration. A thread-local flag would incorrectly register the same globally shared QNames more than once.
- Event-dispatch, page-dismissal, and plugin-script scope main-thread-only DCHECKs were removed as part of making the scopes meaningful on both owner threads; scope-depth checks remain. EventDispatchForbiddenScope now queries the current thread’s count instead of returning false for every worker.
- The animation debug log-once flag uses atomic exchange to remain once-per-process without a same-value race.

## Web research and approach comparison

Checked:
- [Chromium 153 node IDs](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/third_party/blink/renderer/core/dom/dom_node_ids.cc)
- [Chromium 153 NoDestructor documentation](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/base/no_destructor.h), especially its function-local-static thread-safety guarantee and recommendation to use plain statics for trivial types.
- [C++ call_once](https://en.cppreference.com/w/cpp/thread/call_once.html)
- [Atomic fetch_add](https://en.cppreference.com/w/cpp/atomic/atomic/fetch_add.html) and compare-exchange documentation from the QualifiedName pass.

Compared shared atomics/locks against per-thread state: scope policy and heap ownership require TLS, not merely atomic pointers. Globally allocated scalar IDs remain atomic. For once-only trigger registration, initially tried std::call_once, but Chromium cpplint rejects `<mutex>`; the simpler function-local constant initializer provides the same required completion barrier without a new include/dependency. base::NoDestructor<bool> is explicitly inappropriate for a trivial type.

## File:line list

Paths are relative to `third_party/blink/renderer/core/`; line numbers match uploaded mirrors. Include additions and declaration changes are also recorded exhaustively in `changed-lines.txt`.

| Files / lines | Change |
|---|---|
| `html/html_element.cc:833-845` | One-time completed registration using static constant lambda initializer. |
| `css/post_style_update_scope.cc:16-17`, `.h:134` | TLS `current_`. |
| `css/style_attribute_mutation_scope.cc:47-53`, `.h:56-59` | TLS count, current element, notification/delivery flags. |
| `dom/events/scoped_event_queue.cc:36,70-73`, `.h:59-64` | Per-thread Oilpan-owning queue; removed global instance and initializer. |
| `dom/events/event_dispatch_forbidden_scope.cc:10`, `.h:21-45` | TLS debug scope count and worker-aware scope/query behavior. |
| `dom/node_child_removal_tracker.cc:31-32`, `.h:52` | TLS removal-stack head. |
| `dom/range.cc:120,126,133,135` | TLS RangeUpdateScope count and DCHECK current-range pointer. |
| `dom/document.cc:453-455,749,1000-1001`, `.h:1522-1523,2848` | Per-thread DCHECK live-document set; atomic global tree versions. |
| `dom/document_lifecycle.cc:41-42` | TLS deprecated-transition stack. |
| `dom/dom_node_ids.cc:22-36,75` | Atomic global ID allocator with CAS wraparound; atomic test setter. |
| `layout/layout_shift_tracker.cc:40,43-44`, `.h:120,159` | TLS reattach and containing-block scope stacks. |
| `layout/custom/custom_layout_scope.cc:9-10`, `.h:65` | TLS custom-layout scope pointer. |
| `layout/disable_layout_side_effects_scope.cc:9`, `.h:30` | TLS side-effect suppression count. |
| `layout/physical_box_fragment.cc:47-48`, `.h:84` | TLS DCHECK post-layout allowance count. |
| `layout/ink_overflow.cc:58`, `.h:288` | TLS DCHECK read-unset-as-none count. |
| `layout/inline/abstract_inline_text_box.cc:16,31-34,81,87-88` | Per-thread Oilpan-owning cache, TLS optional-instance pointer; preserves no allocation on destruction before first use. |
| `animation/animation.cc:107-109,150-151` | Atomic debug once flag and sequence counter. |
| `animation/animation_clock.cc:43,46-47,67-70`, `.h:87-89,104` | Atomic task-clock counter and explicit atomic accesses. |
| `frame/page_dismissal_scope.cc:11-23` | TLS dismissal depth; worker-safe scope entry/query. |
| `page/plugin_script_forbidden_scope.cc:11-23` | TLS plugin-script prohibition depth; worker-safe scope entry/query. |

## Validation

- Fresh snapshots fetched before editing. Each remote preimage was SHA-256 checked immediately before its scp upload; every uploaded file was checked against its edited local mirror.
- All 32 changed-line Chromium `clang-format --dry-run --Werror` checks passed. `--sort-includes=false` avoids unrelated pre-existing include-order churn; entire large files were deliberately not reformatted.
- Depot_tools cpplint ran remotely. Baseline comparison of all 32 mirrors: **105 warnings before, 105 after; zero new warnings**. See `remote-lint.txt`, `lint-before.txt`, `lint-work.txt`, and `lint-comparison.txt`. Some local warnings reflect mirrored include paths; comparisons normalize those paths.
- No compilation or runtime tests were performed. Owner should build/run existing DOMNodeIds tests (including Overflow), animation-clock tests, and concurrent main/render DOM-style-layout-teardown stress under TSan with DCHECK enabled. Concurrent first attribute handling should verify one completed registration; two Oilpan threads should get distinct queues/cache instances and independent nested scope counters.

## Remaining qualifications / follow-ups

1. **Task-clock semantics:** per explicit request the task counter is atomic, still process-wide. This removes its data race, but a main-thread task start can still change a dynamically updating worker clock’s observed task epoch mid-task. Per-owner-thread task epochs or disabling dynamic updates on the render document remain a semantic follow-up. The parent was notified before applying this choice.
2. **Bounded-ID wraparound:** ordinary concurrent allocations share one atomic sequence. Existing bounded-ID reuse behavior is retained. After a full wrap (or the test reset hook), thread-local IdToNodeMap checks cannot detect live collisions in another thread’s map. Strict global live-ID uniqueness across exhaustion requires a separate allocator/namespace decision; it is not solved by an atomic increment alone.
3. Previously identified CSSStyleDeclaration caches, selector-statistics map, runtime LayoutTheme state, and conditional ordinary-page/widget pause/input globals were not changed in this specifically requested scope pass. The earlier `audit/qualified-name/REPORT.md` records them; its entries for the scope/counter globals fixed here are now superseded.
4. The broader rendering graph still needs TSan/owner-thread auditing. These changes do not authorize sharing Documents, Elements, events, scope objects, or Oilpan GC objects themselves across owner threads.

Artifacts: `before/`, `work/`, `changes.patch`, `changed-files.json`, `changed-lines.txt`, `remote-sha256.txt`, formatting/lint logs, and fetched API context. All edits were exact replacements in fetched mirrors followed by scp; only these 32 source files were uploaded in this pass.
