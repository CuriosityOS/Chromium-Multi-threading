# QualifiedName concurrency fix and remaining global-state audit

Target: `ssh core:/root/cr153/src`, Chromium 153.0.8010.55, Linux. Audit snapshots were taken on 2026-09-26. Other work is occurring in this checkout; line references below describe the inspected snapshots and may drift.

## Remote files changed

Only these three files were written remotely (under `third_party/blink/renderer/core/dom/`):

- `qualified_name.h`
- `qualified_name.cc`
- `qualified_name_test.cc`

Fetched preimages are in `before/`, edited mirrors in `work/`, unified diff in `changes.patch`, and uploaded SHA-256 hashes in `remote-sha256.txt`. Remote preimages were compared against the original snapshots before upload, and uploaded files were verified against the edited mirrors. No git operations or builds were run. The prior 95 Persistent-to-per-thread conversions were not changed.

## Fix

- `existing_hash_` is now a full-width **const unsigned**, calculated after the canonical AtomicString components have been constructed. Hash lookups no longer perform lazy writes. This also avoids hashing uncanonicalized raw constructor arguments.
- `local_name_upper_` is now a **const AtomicString**, initialized before cache publication. `LocalNameUpper()` and the retained `LocalNameUpperSlow()` both return the immutable member. Null and unchanged uppercase values do not trigger repeated writes.
- The trigger index no longer shares bitfield storage with the hash. It is `std::atomic<unsigned>`, read once per query with relaxed ordering; registration uses a strong CAS to preserve the single-registration invariant. It is a scalar value, not a publication flag for other data. Transitions never change static-vs-dynamic status.
- Added cache-lock assertion at `GetQualifiedNameCache()` and locked `ReserveCapacityForSize()`. The reserve lock is released before constructing global names, avoiding recursive acquisition.
- Retained the existing atomic-refcount/cache-lock protocol: the last decrement, cache erasure, and destruction remain serialized against cache lookup plus AddRef. Non-final releases use CAS and cannot perform the 1-to-0 transition outside the cache lock.
- Updated the layout-size surrogate. The Linux x86-64 layout remains 48 bytes by member layout analysis; the existing ASSERT_SIZE remains the build-time check (not compiled here).

Trade-off: uppercase conversion now happens once at creation of each interned impl even if nobody asks for uppercase. It can allocate another interned string and extends cache-lock hold time. No new production dependency, per-impl mutex, or extra allocation for synchronization. Shared access still requires valid ownership/publication of the QualifiedName handle; simultaneous mutation of the same handle itself is not supported. Global name initialization remains a startup operation that must finish before worker use.

## Web research / options

Checked official online source, including the pinned version rather than assuming current main APIs match:

- [Chromium 153 QualifiedName](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/third_party/blink/renderer/core/dom/qualified_name.h)
- [Chromium 153 AtomicString](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/third_party/blink/renderer/platform/wtf/text/atomic_string.h)
- [Chromium Lock / AutoLock](https://chromium.googlesource.com/chromium/src/+/main/base/synchronization/lock.h)
- [Chromium 153 SimpleThread](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/base/threading/simple_thread.h)
- [Chromium 153 WaitableEvent](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/base/synchronization/waitable_event.h)
- [Chromium 153 BindLambdaForTesting](https://chromium.googlesource.com/chromium/src/+/153.0.8010.55/base/test/bind.h)
- [Atomic compare-exchange ordering and signatures](https://en.cppreference.com/w/cpp/atomic/atomic/compare_exchange)

Considered retaining lazy values with atomics / one-time synchronization versus constructing immutable derived values before publication. Chose the latter for KISS: no racing fast-path reads, no mutable reference escaping a lock, no null sentinel ambiguity, no pointer reclamation protocol. The existing atomic and base-lock facilities suffice. Same-value writes were treated as real data races.

## Validation and tests for build owner

- Remote `clang-format --dry-run --Werror` on all three files: **passed** (Chromium depot_tools formatter, version 23).
- Whitespace checks and SHA-256 upload verification: **passed**.
- Remote depot_tools `cpplint.py`: five warnings, all reproduced in baseline snapshots (two non-const-reference warnings, two existing placement-new C-style casts, existing missing `<utility>` include). No new warnings; an existing braces warning was removed. See `validation.txt`, `lint-before.txt`, `lint-work.txt`, `lint-comparison.txt`.
- No compilation or test execution was performed, per instruction.

Added tests (in the existing test file, no BUILD changes):

1. `QualifiedNameTest.UppercaseAndHash`: null, empty, mixed ASCII/non-ASCII names, hash agreement, empty namespace normalization, stable uppercase reference.
2. `QualifiedNameTest.ConcurrentSharedImplReadsAndCopies`: concurrent hash/uppercase access, retained slow accessor, canonical lookup, and refcounted copies.
3. `QualifiedNameTest.ConcurrentInterningAndLastRelease`: no anchor QName, concurrent repeated lookup/copy/final destruction of the same intern key.
4. `QualifiedNameTest.ConcurrentTriggerRegistrationAndReads`: static index registration racing reads/copies/hash, with a privately owned test-only static impl.

Suggested owner runs after their build: `blink_unittests --gtest_filter=QualifiedNameTest.*`, then the concurrent tests repeatedly under TSan. Equal outputs alone do not validate the absence of races. Also stress a real main-thread DOM plus WorkerBackingThread document doing first HTML attribute handling, style mutation, layout, animation, node removal, and teardown concurrently. The unit tests do not create an isolate/Oilpan render page and do not cover all downstream global state.

## Highest-priority remaining races — NOT modified

All paths below are relative to `third_party/blink/renderer/core/`. These are source-level findings, not TSan-confirmed executions. Feature-conditional sites are called out; a nonordinary Page does not automatically reach ordinary-page/widget code.

### P0: cross-thread scope pointers / cross-Oilpan objects

| Area / locations | Shared state and consequence |
|---|---|
| `css/post_style_update_scope.cc:16-45` | `PostStyleUpdateScope::current_` is a process-global pointer to a stack scope. Another thread sees the wrong outermost scope; animation/pseudo updates can go into another document's HeapHashSet/HeapVector. An atomic pointer alone would not fix the ownership error. |
| `css/style_attribute_mutation_scope.cc:47-50,63-119` | `scope_count_`, `current_element_`, `should_notify_inspector_`, `should_deliver_` are global. Concurrent style mutations can be mistaken for nested mutations and use another thread's Element / lose delivery. Scope state needs owner-thread isolation. |
| `dom/events/scoped_event_queue.cc:42-96` | Global `ScopedEventQueue::instance_`, its scoping counter, and queued Oilpan Event vector are mutable. Both lazy initialization and later queue operations race; locking the pointer does not make a shared heap-owned Event queue valid. |
| `dom/node_child_removal_tracker.cc:31`, `.h:55-67`; `dom/range.cc:82-135` | Global `NodeChildRemovalTracker::last_` and `RangeUpdateScope::{scope_count_,current_range_}` hold live stack/DOM pointers. Concurrent removal/range work can traverse another thread's stack or apply updates to the wrong range. |
| `layout/layout_shift_tracker.cc:40,43`, `.h:141-159`; `layout/custom/custom_layout_scope.cc:9` | Reattach/ContainingBlock `top_` and custom-layout `current_scope_` are shared stack pointers. Concurrent style/layout corrupts nesting and can access another thread's stack/heap. Custom-layout entry is feature-dependent. |
| `layout/inline/abstract_inline_text_box.cc:29-84` | Global lazily initialized `AbstractInlineTextBoxCache::s_instance_` owns a Persistent GC map. Accessibility/text-box operations can race and mix objects from different Oilpan heaps. Conditional on those paths being enabled. |

Debug-only but early blocker: `dom/document.cc:449-454,1145` still has `LiveDocumentSet()` as **`DEFINE_STATIC_LOCAL(blink::Persistent<WeakDocumentSetHolder>, ...)`**, inside DCHECK_IS_ON. Both Document constructors insert into the same WeakMember set. This is a remaining namespaced-Persistent site, not a request to redo the already converted 95 sites. Also `dom/document_lifecycle.cc:41,55-60,187-189` has shared `g_deprecated_transition_stack` in DCHECK builds.

### P0/P1: unconditional/shared counters and incorrect scope semantics

- `dom/document.cc:746-747,997-998`, `dom/document.h:1521`: **`Document::global_tree_version_`** is incremented at construction and DOM version updates. This is reached by both ordinary and render documents; lost updates / duplicate version stamps are not harmless.
- `dom/dom_node_ids.cc:19-26`: **`g_last_id`** remains plain even though `IdToNodeMap()` is now per-thread. Simultaneous NextId calls race and can duplicate IDs. Fix must preserve the intended ID namespace and wraparound semantics. `weak_identifier_map.h:84` has a similar generic counter; its macro still contains Persistent, but current production DOMNodeIds uses the separate implementation above (do not confuse them).
- `animation/animation_clock.cc:43,46,66`, `.h:86`: **`currently_running_task_`** is written by NotifyTaskStart and read by animation clocks. It is a task-domain counter: making it atomic alone still lets the main thread invalidate a worker's same-task clock semantics.
- `animation/animation.cc:148-150`: **`NextSequenceNumber()::next`** uses plain `++` for animation construction/order. `first_call` in the histogram macro at line 106 is another mutable shared flag when metrics paths run.
- `layout/disable_layout_side_effects_scope.cc:9`, `.h:21-30`: **`count_`** globally disables side effects for unrelated threads. Atomics alone would retain the wrong behavior.
- `layout/physical_box_fragment.cc:47` (`AllowPostLayoutScope::allow_count_`) and `layout/ink_overflow.cc:58` (`read_unset_as_none_`) are additional shared scope counters, predominantly DCHECK validation state. `dom/events/event_dispatch_forbidden_scope.cc:10` likewise has a shared DCHECK scope counter.

### Frame / page: teardown is relevant even for nonordinary pages

- `frame/page_dismissal_scope.cc:12-26`: **`page_dismissal_scope_count`**.
- `page/plugin_script_forbidden_scope.cc:12-27`: **`g_plugin_script_forbidden_count`**.
- Both are non-atomic globals with main-thread DCHECKs. `Document` shutdown/dismissal uses these scopes (`dom/document.cc` around 4545 and 4633-4634), and `LocalFrame::DetachImpl()` uses the plugin scope (`frame/local_frame.cc` around 732). Worker teardown must be audited, not just initial layout. Scope counters should not leak policy between unrelated threads.
- Conditional ordinary/widget follow-ups: `page/scoped_page_pauser.cc:35` **`g_suspension_count`**, `page/scoped_browsing_context_group_pauser.cc:20` mutable **`counts` std::map**, `frame/web_frame_widget_impl.cc:390,451` mutable **`values` std::map / ignore_input_events_**. A nonordinary Page does not enter CreateOrdinary's pauser lookup automatically. These become races if corresponding pause/input/widget paths execute on both threads; map operator[] mutates even on a nominal query.

### Other mutable caches / theme state

- `css/css_style_declaration.cc:124-146`: shared **CSSPropertyIDMap** mutated during named-property lookup; the property-name vector at line 263 is also lazily filled after static construction. Relevant if worker code uses CSSStyleDeclaration named access/enumeration.
- `css/element_rule_collector.cc:386-420`: shared **SelectorStatisticsRuleMap** accumulates and clears selector statistics. Relevant with selector-performance instrumentation enabled.
- `layout/layout_theme.cc:177-192,469+`: shared selection-color state is written by SetSelectionColors and read by rendering; singleton theme `custom_focus_ring_color_` is written/read at 899-915. Runtime UI/theme changes concurrent with worker style/paint need a synchronized update/snapshot design.

### Immediate adjacent blocker outside requested directories

**`html/html_element.cc:833-850`, `HTMLElement::TriggersForAttributeName()`:**

```
static bool registered_triggers = false;
if (!registered_triggers) {
  registered_triggers = true;
  // loop: RegisterHTMLAttributeTriggersIndex(index)
}
```

The plain flag races and is published **before** the registration loop completes. A second thread may miss attribute callbacks by observing an unregistered index; two entrants can double-register (and hit the QualifiedName registration CHECK, both before and after this patch). Fix the caller with a true once-completion barrier or complete registration before worker startup. The per-QName atomic index fixes its own storage race, **not** this whole-table publication bug. This should be addressed before concurrent first-use testing.

Already converted `AllPages`/`OrdinaryPages`, `GetLocalFramesMap`, CSSDefaultStyleSheets and other inspected per-thread Persistent sites were not reported as outstanding shared caches.
