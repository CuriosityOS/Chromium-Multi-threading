# Audit 3 — remaining render-thread globals

**Proposals only. No remote edits, builds, tests, or git operations.** Audited current Linux `core:/root/cr153/src`. Paths below are relative to `third_party/blink/renderer/`; line numbers identify fetched preimages. Details, reachability qualifications, and caveats: [`audit3/DETAILS.md`](audit3/DETAILS.md).

## Ranked findings

| Risk | Source | Failure / minimal proposal |
|---|---|---|
| **P0** | `core/display_lock/display_lock_utilities.cc:34` | Full lifecycle shares `memoizer_`, pointing into another thread's stack and Oilpan hash sets. TLS pointer; matching header required. |
| **P0** | `core/paint/timing/paint_timing_detector.cc:395` | Global block-paint hook `top_` crosses stack/Document ownership; possible use-after-return. TLS pointer; matching header required. |
| **P0** | `core/paint/decoration_line_painter.cc:380` | Wavy-cache replacement destroys geometry while another painter retains a reference. Per-thread cache. |
| P1 | `core/css/css_computed_style_declaration.cc:106`, `css_style_declaration.cc:124,263`; `core/svg/svg_element.cc:324`, `svg_animate_element.cc:83`; `core/layout/forms/layout_text_control.cc:156` | Concurrent lazy vector/map population: partial publication, reallocations, table corruption. Per-thread caches. |
| P1 | `core/html/html_slot_element.cc:572-574` | Shared LCS/backtracking tables mix separate slot distributions. Per-thread scratch. |
| P1 | `platform/graphics/compositor_element_id.cc:12` | Lost increments / duplicate compositor identities. Process-wide relaxed atomic, **not TLS**. |
| P1, conditional | `core/layout/layout_image_resource.cc:176,182`; `core/paint/theme_painter_default.cc:854-866`; `core/html/canvas/html_canvas_element.cc:1094,1100`; `platform/graphics/image.cc:76` | Broken/search-control/null Image singletons retain mutable decoder/frame/dark-mode state despite atomic refcounts. Per-thread Images. |
| P1, conditional | `platform/text/hyphenation/hyphenation_minikin.cc:58`; `platform/text/platform_locale.cc:46,188` | Linux Minikin uses shared sequence-bound Mojo Remote; localized controls share lazy Locale/ICU state. Per-thread instances. |
| Ownership | `core/animation/underlying_value_owner.cc:41` | `NullValueWrapper` hides a Persistent missed by the direct-Persistent sweep. Per-thread wrapper; payload itself is an immutable null sentinel. |

## Specs: `.cc` only versus header-dependent

All nine files are in `/Users/core/chromium-threading/edits/` and use the requested redit format.

**No headers:** `21-audit3-cc-{caches,ids,images,dcheck}.txt`. DCHECK spec covers `tree_ordered_map.cc:49`, `tree_scope_adopter.cc:277`, `paint_layer.cc:2734`; computed-style diagnostic dedup is included with its cache fix.

**Matching header changes required; separately review/apply:**
- `21-audit3-header-scopes.txt`: `display_lock_utilities`, `paint_timing_detector`, `frame_painter`, `pre_paint_disable_side_effects_scope`, `paint_layer`, `paint_layer_scrollable_area`, `svg_layout_support`, `ignore_paint_timing_scope`. TLS stack/policy state; delayed-clamp list was already per-thread but its depth was not.
- `21-audit3-header-geometry.txt`: `geometry_mapper_{transform,clip}_cache` generations (`.cc:16`). TLS avoids unrelated invalidation midway through geometry/hit-test operations; atomics alone do not.
- `21-audit3-header-script-policy.txt`: `script_forbidden_scope` lifecycle counter. TLS plus worker-aware query/reset; removes obsolete main-only lifecycle assertions.
- `21-audit3-header-custom-elements.txt`: `ce_reactions_scope`, `custom_element_construction_stack`. Conditional on replica reactions/upgrades; TLS stack/nesting, not permission to share callbacks/isolate objects.
- `21-audit3-header-metrics.txt`: `instance_counters` node count → relaxed atomic; `font_performance` keeps documented main-only metrics by guarding scope/reset/lifecycle entry points.

## Validation / next checks

Validated **77 unique, non-overlapping old blocks across 47 source files** against freshly read remote sources. Changed-line Chromium clang-format passed; cpplint: **57 baseline / 57 proposed warnings, zero new**. Results: [`audit3/validation.txt`](audit3/validation.txt). Formatting/lint used local proposed mirrors; remote formatter only read stdin. Manifest and source hashes are retained in `audit3/`.

Next: parent-run DCHECK+TSan concurrent lifecycle/paint/geometry with content-visibility, wavy text, slot redistribution, SVG animation, form controls, cold computed-style caches, and teardown. Add two-thread ID-uniqueness and interleaved-scope tests; exercise conditional image/hyphenation/custom-element paths when enabled.

## Remaining serious issues / exclusions

- **MemoryCache is not a one-line TLS fix:** Oilpan state, main task runner, registrations, and shared dump provider must agree. Generic fetcher guards do not cover all direct ImageLoader/stylesheet-resource callers; ImageResource still has main-thread CHECKs. Resource-loading design remains separate.
- Runtime LayoutTheme selection/focus colors, Linux font/render settings, and scrollbar-theme updates need synchronized publication—not stale per-thread defaults. Main-only font prewarming also needs an owner-thread guard/dispatch rather than only TLS flags.
- Skipped the four explicitly already-fixed globals, converted Persistent sites, tests, devtools-only paths, and non-Linux-only implementations. Ordinary-page/widget pause/input globals remain conditional. Read-only initialized tables, immutable TimeClamper/timing presets, and worker-bypassed ToBlinkStringFast were not labeled races.
- TLS does not authorize cross-thread DOM/Oilpan sharing. Leaky per-thread caches increase retained memory; shutdown/LSan and context-dependent CSS exposure semantics still need coverage. This is not a proof that all reachable code is thread-safe.

## Web research

Checked [TLS/static initialization](https://en.cppreference.com/w/cpp/language/storage_duration.html), [atomic fetch_add](https://en.cppreference.com/cpp/atomic/atomic/fetch_add), [Mojo sequence affinity](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/mojo/public/cpp/bindings/README.md), and [scoped_refptr::release](https://chromium.googlesource.com/chromium/src/+/HEAD/base/memory/scoped_refptr.h), then verified current checkout API fit. Compared locks/completed-once initialization with owner-thread caches, and atomics with TLS. Chose minimal ownership isolation, global atomic IDs, and main-only metric guards. No dependencies or synchronization-framework rewrite.
