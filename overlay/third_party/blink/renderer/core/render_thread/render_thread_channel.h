// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_CHANNEL_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_CHANNEL_H_

#include <atomic>

#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "base/time/time.h"
#include "third_party/blink/renderer/core/core_export.h"
#include "third_party/blink/renderer/platform/wtf/text/wtf_string.h"
#include "third_party/blink/renderer/platform/wtf/thread_safe_ref_counted.h"
#include "third_party/blink/renderer/platform/wtf/vector.h"
#include "ui/gfx/geometry/rect_f.h"

namespace blink {

// One entry of the DOM journal. The main thread records these as the DOM
// changes; the render thread replays them onto its replica document.
//
// Node ids are assigned by the main thread. Id 1 is always the document.
// Strings are plain WTF strings: StringImpl reference counts and hashes are
// atomic, and the AtomicString table is process-global, so they can be
// handed from the main thread to the render thread as-is.
struct RenderThreadOp {
  enum class Type : uint8_t {
    // node, ns, prefix, local_name
    kCreateElement,
    // node, text
    kCreateText,
    kCreateComment,
    // node, local_name = name, ns = public id, prefix = system id
    kCreateDoctype,
    // node = shadow root id, parent = host id, int_value = ShadowRootMode,
    // int_value2 = bit 0: delegates focus, bit 1: manual slot assignment.
    kAttachShadowRoot,
    // node, ns, prefix, local_name, text = value
    kSetAttribute,
    // node, ns, prefix, local_name
    kRemoveAttribute,
    // parent, node, before (0 = append)
    kInsert,
    // node
    kRemove,
    // parent
    kRemoveAllChildren,
    // node, text
    kSetText,
    // node, text: complete style sheet text for a <link rel=stylesheet> or a
    // <style> whose sheet was changed through the CSSOM.
    kSetSheetText,
    // node, int_value = ElementState, int_value2 = 0/1
    kSetElementState,
    // int_value = width, int_value2 = height (physical pixels),
    // float_value = layout zoom factor (includes the device scale factor).
    kSetViewport,
    // float_value = x, float_value2 = y (root scroll offset)
    kSetScrollOffset,
    // int_value = Document::CompatibilityMode
    kSetCompatMode,
    // Script scrolled an element (scrollLeft/scrollTop setters, scrollTo(),
    // scrollBy()) or, if node is the document, the window.
    // node, float_value = left, float_value2 = top,
    // int_value = bit 0: has left, bit 1: has top, bit 2: relative (scrollBy).
    kScrollElement,
  };

  enum class ElementState : int32_t {
    kHovered = 0,
    kActive = 1,
    kFocused = 2,
    kChecked = 3,
  };

  Type type;
  uint32_t node = 0;
  uint32_t parent = 0;
  uint32_t before = 0;
  int32_t int_value = 0;
  int32_t int_value2 = 0;
  float float_value = 0;
  float float_value2 = 0;
  String ns;
  String prefix;
  String local_name;
  String text;
};

// A synchronous layout or style query made by main-thread script (element
// geometry, computed style, hit testing). The main thread never lays out a
// document that has a render thread: it commits the journal, sends the query
// to the page's render thread and blocks until the render thread has brought
// the replica's style and layout up to date and filled in the answer.
struct RenderThreadQuery {
  enum class Type : uint8_t {
    // Answer in `number`. `node` is an element.
    kOffsetLeft,
    kOffsetTop,
    kOffsetWidth,
    kOffsetHeight,
    kClientLeft,
    kClientTop,
    kClientWidth,
    kClientHeight,
    kScrollLeft,
    kScrollTop,
    kScrollWidth,
    kScrollHeight,
    // Answer in `result_node`. `node` is an element.
    kOffsetParent,
    // Answer in `rects[0]`. `node` is an element.
    kBoundingClientRect,
    // Answer in `rects`. `node` is an element.
    kClientRects,
    // `node` is an element, `text` the property name, `pseudo` the pseudo
    // element argument of getComputedStyle(). Answer in `text`.
    kComputedStyle,
    // Answer in `text`. `node` is an HTML element.
    kInnerText,
    // `node` is a tree scope (document or shadow root), `point` in CSS
    // pixels. Answer in `result_node`.
    kElementFromPoint,
    // As above. Answer in `result_nodes`, topmost first.
    kElementsFromPoint,
    // Input event hit test. `node` is the document, `point` in document
    // coordinates. Answer: `result_node` = inner node (or its nearest
    // replicated ancestor), `result_x/y` = point in that node's coordinates.
    kHitTest,
    // Answer in `number`: the element's FocusableState (focusability depends
    // on style and layout). `node` is an element.
    kFocusableState,
    // MouseEvent offsetX/Y and layerX/Y. `node` is the event target, `x`/`y`
    // the event's absolute location, `number` the layout zoom factor.
    // `rects[0].origin()` / `rects[1].origin()` carry the offset and layer
    // locations in (as page coordinates) and out.
    kMouseRelativePosition,
    // Range.getClientRects() / getBoundingClientRect(). `node` is the start
    // container, `node2` the end container, `x`/`y` the start/end offsets.
    // Answer in `rects`.
    kRangeClientRects,
    kRangeBoundingClientRect,
    // window.innerWidth / innerHeight / scrollX / scrollY. `node` is the
    // document. Answer in `number`.
    kInnerWidth,
    kInnerHeight,
    kWindowScrollX,
    kWindowScrollY,
  };

  Type type;
  uint32_t node = 0;
  uint32_t node2 = 0;
  String text;
  String pseudo;
  double x = 0;
  double y = 0;

  // Answer.
  bool answered = false;
  double number = 0;
  uint32_t result_node = 0;
  double result_x = 0;
  double result_y = 0;
  Vector<uint32_t> result_nodes;
  Vector<gfx::RectF> rects;
};

// Thread-safe queue of journal entries between the main thread (producer)
// and the render thread (consumer).
//
// The main thread marks a "commit point" at the end of every task so the
// render thread never shows the DOM in the middle of a task. If the main
// thread stays inside a single task for longer than `stale_after` (a long
// JavaScript task), the render thread takes the uncommitted entries anyway so
// that the page keeps up with what the script has done so far.
class CORE_EXPORT RenderThreadChannel
    : public ThreadSafeRefCounted<RenderThreadChannel> {
 public:
  RenderThreadChannel() = default;
  RenderThreadChannel(const RenderThreadChannel&) = delete;
  RenderThreadChannel& operator=(const RenderThreadChannel&) = delete;

  // Main thread. Returns true if the queue was empty before this entry.
  bool Push(RenderThreadOp op);
  // Main thread. Returns true if there was something to commit.
  bool Commit();
  // Main thread. Returns true if the caller should post a wake-up task to the
  // render thread (i.e. no wake-up is already pending).
  bool MarkWakePending();

  // Render thread. Returns the entries that are ready to be applied. Sets
  // `has_uncommitted` if entries remain queued.
  Vector<RenderThreadOp> TakeReadyOps(base::TimeTicks now,
                                      base::TimeDelta stale_after,
                                      bool* has_uncommitted);
  // Render thread.
  void ClearWakePending();

 private:
  friend class ThreadSafeRefCounted<RenderThreadChannel>;
  ~RenderThreadChannel() = default;

  base::Lock lock_;
  Vector<RenderThreadOp> ops_ GUARDED_BY(lock_);
  wtf_size_t committed_ GUARDED_BY(lock_) = 0;
  base::TimeTicks oldest_uncommitted_ GUARDED_BY(lock_);
  std::atomic<bool> wake_pending_{false};
};

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_CHANNEL_H_
