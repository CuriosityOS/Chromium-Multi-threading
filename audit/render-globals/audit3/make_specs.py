#!/usr/bin/env python3
"""Generate LOCAL redit proposals only; never writes into the remote checkout."""
from collections import defaultdict
from pathlib import Path
import difflib
import json
import re

ROOT = Path(__file__).resolve().parent
SNAP = ROOT / 'snapshots'
OUT = ROOT.parents[2] / 'edits'
PREFIX = 'third_party/blink/renderer/'
groups = defaultdict(list)


def add(group, file, old, new):
    text = (SNAP / file).read_text()
    assert text.count(old) == 1, (file, text.count(old), old)
    assert old != new
    groups[group].append(dict(path=PREFIX + file, oldText=old, newText=new,
                              line=text[:text.index(old)].count('\n') + 1))


def include_tls(group, file):
    text = (SNAP / file).read_text()
    inc = '#include "third_party/blink/renderer/platform/wtf/per_thread_static.h"'
    if inc in text:
        return
    includes = list(re.finditer(r'^#include "third_party/blink/renderer/platform/wtf/[^\n]+', text, re.M))
    if not includes:
        includes = list(re.finditer(r'^#include "third_party/blink/renderer/platform/[^\n]+', text, re.M))
    anchor = includes[0].group() if includes else list(re.finditer(r'^#include "[^\n]+', text, re.M))[-1].group()
    add(group, file, anchor, anchor + '\n' + inc)


def macro_tls(group, file, needle):
    include_tls(group, file)
    add(group, file, needle, needle.replace('DEFINE_STATIC_LOCAL', 'DEFINE_PER_THREAD_STATIC_LOCAL'))


def pair(group, stem, definition, declaration, const=True):
    add(group, stem + '.cc', definition, ('constinit thread_local ' if const else 'thread_local ') + definition)
    add(group, stem + '.h', declaration, declaration.replace('static ', 'static thread_local ', 1))

# No header changes: genuinely mutable data or unsafe lazy publication.
g = 'cc-caches'
for file, needles in {
    'core/css/css_computed_style_declaration.cc': [
        'DEFINE_STATIC_LOCAL(HashSet<CSSPropertyID>, property_id_set, ());',
        'DEFINE_STATIC_LOCAL(Vector<const CSSProperty*>, properties, ());'],
    'core/css/css_style_declaration.cc': [
        'DEFINE_STATIC_LOCAL(CSSPropertyIDMap, map, ());',
        'DEFINE_STATIC_LOCAL(PreAllocatedPropertyVector, property_names, ());'],
    'core/svg/svg_animate_element.cc': [
        'DEFINE_STATIC_LOCAL(AttributeToPropertyTypeMap, css_property_map, ());'],
    'core/animation/underlying_value_owner.cc': [
        'DEFINE_STATIC_LOCAL(NullValueWrapper, null_value_wrapper, ());'],
    'core/paint/decoration_line_painter.cc': [
        'DEFINE_STATIC_LOCAL(std::optional<WavyCache>, wavy_cache, (std::nullopt));'],
    'core/html/html_slot_element.cc': [
        'DEFINE_STATIC_LOCAL(LCSTable*, lcs_table, (new LCSTable(kLCSTableSizeLimit)));',
        'DEFINE_STATIC_LOCAL(BacktrackTable*, backtrack_table,'],
    'platform/text/hyphenation/hyphenation_minikin.cc': [
        'DEFINE_STATIC_LOCAL(mojo::Remote<mojom::blink::Hyphenation>, service,'],
}.items():
    include_tls(g, file)
    for needle in needles:
        add(g, file, needle, needle.replace('DEFINE_STATIC_LOCAL', 'DEFINE_PER_THREAD_STATIC_LOCAL'))
add(g, 'core/svg/svg_element.cc',
    'static HashMap<StringImpl*, CSSPropertyID>* property_name_to_id_map = nullptr;',
    'static constinit thread_local HashMap<StringImpl*, CSSPropertyID>*\n      property_name_to_id_map = nullptr;')
add(g, 'core/layout/forms/layout_text_control.cc',
    'static HashSet<AtomicString>* font_families_with_invalid_char_width_map =',
    'static constinit thread_local HashSet<AtomicString>*\n      font_families_with_invalid_char_width_map =')
add(g, 'platform/text/platform_locale.cc', 'Locale* g_default_locale;',
    'constinit thread_local Locale* g_default_locale = nullptr;')
add(g, 'platform/text/platform_locale.cc',
    'Locale& Locale::DefaultLocale() {\n  DCHECK(IsMainThread());',
    'Locale& Locale::DefaultLocale() {')

# Process-wide identity must not become per-thread.
g = 'cc-ids'
f = 'platform/graphics/compositor_element_id.cc'
add(g, f, '#include <limits>', '#include <atomic>\n#include <limits>')
add(g, f, '  static UniqueObjectId counter = 0;\n  return ++counter;',
    '  static constinit std::atomic<UniqueObjectId> counter{0};\n  return counter.fetch_add(1, std::memory_order_relaxed) + 1;')

# Diagnostic state is still written by production paths in DCHECK builds.
g = 'cc-dcheck'
add(g, 'core/dom/tree_ordered_map.cc', 'static int g_remove_scope_level = 0;',
    'static constinit thread_local int g_remove_scope_level = 0;')
add(g, 'core/dom/tree_scope_adopter.cc',
    'static bool g_did_move_to_new_document_was_called = false;\nstatic Document* g_old_document_did_move_to_new_document_was_called_with =',
    'static constinit thread_local bool g_did_move_to_new_document_was_called =\n    false;\nstatic constinit thread_local Document*\n    g_old_document_did_move_to_new_document_was_called_with =')
add(g, 'core/paint/paint_layer.cc', '  static bool check_no_dirty_flags = false;',
    '  static constinit thread_local bool check_no_dirty_flags = false;')

# Cached Image objects contain lazy mutable paint/decoder state even though
# Image's reference count is thread safe. Preserve raw-pointer call sites and
# deliberate singleton lifetime; release() transfers the singleton reference.
g = 'cc-images'
for f in ['core/layout/layout_image_resource.cc', 'core/paint/theme_painter_default.cc',
          'core/html/canvas/html_canvas_element.cc', 'platform/graphics/image.cc']:
    text = (SNAP / f).read_text()
    pattern = r'DEFINE_STATIC_REF\(\s*(?:blink::)?Image,\s*(\w+),\s*\((.*?)\)\);'
    matches = list(re.finditer(pattern, text, re.S))
    assert matches, f
    include_tls(g, f)
    for m in matches:
        name, expression = m.groups()
        expression = ' '.join(expression.split())
        add(g, f, m.group(),
            f'DEFINE_PER_THREAD_STATIC_LOCAL(Image*, {name},\n' +
            f'                               ({expression}.release()));')
add(g, 'platform/graphics/image.cc',
    'Image* Image::NullImage() {\n  DCHECK(IsMainThread());',
    'Image* Image::NullImage() {')

# Header-dependent fixes are deliberately isolated from the .cc-only proposals.
g = 'header-scopes'
pair(g, 'core/display_lock/display_lock_utilities',
     'DisplayLockUtilities::LockCheckMemoizationScope*\n    DisplayLockUtilities::memoizer_ = nullptr;',
     '  static LockCheckMemoizationScope* memoizer_;')
pair(g, 'core/paint/timing/paint_timing_detector',
     'ScopedPaintTimingDetectorBlockPaintHook*\n    ScopedPaintTimingDetectorBlockPaintHook::top_ = nullptr;',
     '  static ScopedPaintTimingDetectorBlockPaintHook* top_;')
pair(g, 'core/paint/frame_painter', 'bool FramePainter::in_paint_contents_ = false;',
     '  static bool in_paint_contents_;')
pair(g, 'core/paint/pre_paint_disable_side_effects_scope',
     'unsigned PrePaintDisableSideEffectsScope::count_ = 0;',
     '  static unsigned count_;')
pair(g, 'core/layout/svg/svg_layout_support',
     'AffineTransform SubtreeContentTransformScope::current_content_transformation_;',
     '  static AffineTransform current_content_transformation_;', const=False)
pair(g, 'core/paint/paint_layer',
     'bool CheckAncestorPositionVisibilityScope::should_check_ = false;',
     '  static bool should_check_;')
for type_, name, init in [('int', 'ignore_depth_', '0'),
                          ('bool', 'is_document_element_invisible_', 'false')]:
    pair(g, 'platform/graphics/paint/ignore_paint_timing_scope',
         f'{type_} IgnorePaintTimingScope::{name} = {init};',
         f'  static {type_} {name};')
for scope in ['FreezeScrollbarsScope', 'DelayScrollOffsetClampScope']:
    f = 'core/paint/paint_layer_scrollable_area.cc'
    old = f'int PaintLayerScrollableArea::{scope}::count_ = 0;'
    add(g, f, old, 'constinit thread_local ' + old)
f = 'core/paint/paint_layer_scrollable_area.h'
add(g, f, '    static bool ScrollbarsAreFrozen() { return count_; }\n\n   private:\n    static int count_;',
    '    static bool ScrollbarsAreFrozen() { return count_; }\n\n   private:\n    static thread_local int count_;')
add(g, f, '    static HeapVector<Member<PaintLayerScrollableArea>>& NeedsClampList();\n\n    static int count_;',
    '    static HeapVector<Member<PaintLayerScrollableArea>>& NeedsClampList();\n\n    static thread_local int count_;')

# Per-owner-thread generations avoid unrelated invalidations halfway through a
# geometry operation, which an atomic global would still permit.
g = 'header-geometry'
for kind, suffix in [('transform', ''), ('clip', '_')]:
    cls = 'GeometryMapper' + kind.title() + 'Cache'
    pair(g, f'platform/graphics/paint/geometry_mapper_{kind}_cache',
         f'unsigned {cls}::s_global_generation{suffix} = 1;',
         f'  static unsigned s_global_generation{suffix};')

# Full lifecycle executes this scope on both threads; checking/resetting must
# also use the new per-thread state, not silently bypass worker protection.
g = 'header-script-policy'
pair(g, 'platform/bindings/script_forbidden_scope',
     'unsigned ScriptForbiddenScope::g_blink_lifecycle_counter_ = 0;',
     '  static unsigned g_blink_lifecycle_counter_;')
f = 'platform/bindings/script_forbidden_scope.h'
add(g, f, '      if (IsMainThread()) [[likely]] {\n        saved_blink_counter_.emplace(&g_blink_lifecycle_counter_, 0);\n      }',
    '      saved_blink_counter_.emplace(&g_blink_lifecycle_counter_, 0);')
old = '''  static bool WillBeScriptForbidden() {
    if (IsMainThread()) [[likely]] {
      return g_blink_lifecycle_counter_ > 0;
    }
    // Blink lifecycle scope is never entered on other threads.
    return false;
  }'''
add(g, f, old, '''  static bool WillBeScriptForbidden() {
    return g_blink_lifecycle_counter_ > 0;
  }''')
add(g, f, '''  static void EnterBlinkLifecycle() {
    DCHECK(IsMainThread());
    ++g_blink_lifecycle_counter_;
  }
  static void ExitBlinkLifecycle() {
    DCHECK(IsMainThread());
    --g_blink_lifecycle_counter_;
  }''', '''  static void EnterBlinkLifecycle() { ++g_blink_lifecycle_counter_; }
  static void ExitBlinkLifecycle() {
    DCHECK(g_blink_lifecycle_counter_);
    --g_blink_lifecycle_counter_;
  }''')

# Conditional on replica custom-element reactions/upgrades actually being run.
g = 'header-custom-elements'
pair(g, 'core/html/custom/ce_reactions_scope',
     'CEReactionsScope* CEReactionsScope::top_of_stack_ = nullptr;',
     '  static CEReactionsScope* top_of_stack_;')
f = 'core/html/custom/ce_reactions_scope.cc'
add(g, f, 'CEReactionsScope* CEReactionsScope::Current() {\n  DCHECK(IsMainThread());',
    'CEReactionsScope* CEReactionsScope::Current() {')
add(g, f, '''  // For speed of the bindings we use a global variable to determine if
  // we have a CEReactionScope. We check that this is only on the main thread
  // otherwise this global variable will have collisions.
  DCHECK(IsMainThread());''',
    '  // Each thread maintains its own reaction-scope stack and isolate.')
pair(g, 'core/html/custom/custom_element_construction_stack',
     'wtf_size_t CustomElementConstructionStackScope::nesting_level_ = 0;',
     '  static wtf_size_t nesting_level_;')

# Preserve explicitly main-thread-only font metrics, rather than quietly
# creating meaningless per-replica aggregates.
g = 'header-metrics'
f = 'platform/fonts/font_performance.h'
add(g, f, '  static void Reset() {\n    primary_font_ = base::TimeDelta();',
    '  static void Reset() {\n    if (!IsMainThread()) {\n      return;\n    }\n    primary_font_ = base::TimeDelta();')
add(g, f, '''    StyleScope() { ++in_style_; }
    ~StyleScope() {
      DCHECK(in_style_);
      --in_style_;
    }''', '''    StyleScope() {
      if (IsMainThread()) {
        ++in_style_;
      }
    }
    ~StyleScope() {
      if (IsMainThread()) {
        DCHECK(in_style_);
        --in_style_;
      }
    }''')
f = 'platform/fonts/font_performance.cc'
for method in ['MarkFirstContentfulPaint', 'MarkDomContentLoaded']:
    old = f'void FontPerformance::{method}() {{'
    add(g, f, old, old + '\n  if (!IsMainThread()) {\n    return;\n  }')
f = 'platform/instrumentation/instance_counters.h'
add(g, f, '''    // There are lots of nodes created. Atomic barriers or locks
    // should be avoided for the sake of performance. See crbug.com/641019
    if (type == kNodeCounter) {
      DCHECK(IsMainThread());
      ++node_counter_;
    } else {''', '''    if (type == kNodeCounter) {
      node_counter_.fetch_add(1, std::memory_order_relaxed);
    } else {''')
add(g, f, '''    if (type == kNodeCounter) {
      DCHECK(IsMainThread());
      --node_counter_;
    } else {''', '''    if (type == kNodeCounter) {
      node_counter_.fetch_sub(1, std::memory_order_relaxed);
    } else {''')
add(g, f, '  PLATFORM_EXPORT static int node_counter_;',
    '  PLATFORM_EXPORT static std::atomic_int node_counter_;')
f = 'platform/instrumentation/instance_counters.cc'
add(g, f, 'int InstanceCounters::node_counter_ = 0;',
    'constinit std::atomic_int InstanceCounters::node_counter_{0};')
add(g, f, '''  if (type == kNodeCounter) {
    DCHECK(IsMainThread());
    return node_counter_;
  }''', '''  if (type == kNodeCounter) {
    return node_counter_.load(std::memory_order_relaxed);
  }''')

# All edits are matched against the same source, even across separate specs.
byfile = defaultdict(list)
for group, edits in groups.items():
    for e in edits:
        byfile[e['path']].append(e)
for file, edits in byfile.items():
    text = (SNAP / file.removeprefix(PREFIX)).read_text()
    spans = sorted((text.index(e['oldText']), text.index(e['oldText']) + len(e['oldText'])) for e in edits)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), file

OUT.mkdir(exist_ok=True)
for group, edits in groups.items():
    data = ''.join(f"@@@ {e['path']}\n<<<<\n{e['oldText']}\n====\n{e['newText']}\n>>>>\n" for e in edits)
    (OUT / f'21-audit3-{group}.txt').write_text(data)
(ROOT / 'spec-manifest.json').write_text(json.dumps(groups, indent=2) + '\n')
print(f'Generated {len(groups)} specs, {sum(map(len, groups.values()))} unique nonoverlapping edits, {len(byfile)} source files. No remote writes.')
