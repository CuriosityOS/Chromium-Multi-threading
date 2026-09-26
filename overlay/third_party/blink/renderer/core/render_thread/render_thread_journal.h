// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_JOURNAL_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_JOURNAL_H_

#include <memory>
#include <optional>

#include "base/memory/scoped_refptr.h"
#include "third_party/blink/public/platform/web_surface_layer_bridge.h"
#include "third_party/blink/renderer/core/core_export.h"
#include "third_party/blink/renderer/core/dom/container_node.h"
#include "third_party/blink/renderer/core/render_thread/render_thread_channel.h"
#include "third_party/blink/renderer/platform/graphics/paint/display_item_client.h"
#include "third_party/blink/renderer/platform/heap/collection_support/heap_hash_map.h"
#include "third_party/blink/renderer/platform/heap/collection_support/heap_hash_set.h"
#include "third_party/blink/renderer/platform/heap/garbage_collected.h"
#include "third_party/blink/renderer/platform/heap/member.h"
#include "third_party/blink/renderer/platform/wtf/allocator/allocator.h"
#include "ui/gfx/geometry/size.h"

namespace cc {
class Layer;
}

namespace blink {

class CSSStyleSheet;
class Document;
class Element;
class HitTestLocation;
class HitTestResult;
class Range;
class LocalFrameView;
class PaintControllerPersistentData;
class QualifiedName;
class RenderThread;
class ShadowRoot;
class SurfaceLayerBridge;
class TreeScope;

// Off-main-thread rendering (--enable-blink-features=OffMainThreadRendering).
//
// The main thread keeps running JavaScript against the real DOM. Every change
// to the DOM that can affect rendering is recorded here as a RenderThreadOp
// and sent to the render thread (see render_thread.h), which keeps a replica
// of the document and runs style, layout, paint and raster for it, producing
// compositor frames on its own. The main thread no longer paints: its
// BeginMainFrame only embeds the render thread's output surface.
//
// One journal exists per outermost main frame document.
class CORE_EXPORT RenderThreadJournal final
    : public GarbageCollected<RenderThreadJournal>,
      public DisplayItemClient,
      public WebSurfaceLayerBridgeObserver {
 public:
  // Attaches a journal to `document` if off-main-thread rendering applies to
  // it. Called at the end of Document::Initialize().
  static void MaybeAttach(Document& document);
  // Stops the document's render thread when it enters the back/forward cache
  // and starts a new one (replicating the current DOM) when it is restored.
  static void SetInBackForwardCache(Document& document, bool in_cache);

  explicit RenderThreadJournal(Document& document);
  ~RenderThreadJournal() override;

  // Called from Document::Shutdown().
  void Detach();

  // DOM hooks, main thread only.
  void ChildrenChanged(const ContainerNode& container,
                       const ContainerNode::ChildrenChange& change);
  void AttributeChanged(const Element& element,
                        const QualifiedName& name,
                        const AtomicString& new_value);
  void InlineStyleChanged(const Element& element);
  // Script scrolled `element`. Returns false if its document has no render
  // thread, in which case the caller scrolls on the main thread as usual.
  static bool Scroll(const Node& element_or_document,
                     std::optional<double> left,
                     std::optional<double> top,
                     bool relative);
  void ElementStateChanged(const Element& element,
                           RenderThreadOp::ElementState state,
                           bool value);
  void ShadowRootAttached(const Element& host, ShadowRoot& root);
  void StyleSheetChanged(const CSSStyleSheet& sheet);
  void CompatibilityModeChanged();

  // Called at the end of every main thread task.
  void CommitTask();

  // The main thread was asked to run style or layout for this document
  // anyway (by code other than the queries below). Returns false if the
  // update should be skipped because the render thread answers for it (see
  // FocusScope); otherwise the update is counted, traced and logged, so that
  // remaining main-thread rendering is visible, and true is returned.
  bool NoteMainThreadRendering(const char* phase, int reason);

  // While alive, focus changes on this thread skip main-thread style and
  // layout: focusability comes from the render thread instead.
  class CORE_EXPORT FocusScope {
    STACK_ALLOCATED();

   public:
    FocusScope();
    FocusScope(const FocusScope&) = delete;
    FocusScope& operator=(const FocusScope&) = delete;
    ~FocusScope();
  };

  // Synchronous layout and style queries from script (offsetWidth,
  // getBoundingClientRect(), getComputedStyle(), elementFromPoint(), ...).
  // The main thread does not lay out a document that has a render thread;
  // these ask the page's render thread and wait for its answer. They return
  // std::nullopt when the node is not part of a replicated document, in which
  // case the caller uses the regular main-thread path.
  static std::optional<double> QueryNumber(const Element& element,
                                           RenderThreadQuery::Type type);
  static std::optional<Element*> QueryOffsetParent(const Element& element);
  static std::optional<double> QueryWindowNumber(const Document& document,
                                                 RenderThreadQuery::Type type);
  static std::optional<Vector<gfx::RectF>> QueryRects(
      const Element& element,
      RenderThreadQuery::Type type);
  static std::optional<String> QueryComputedStyle(const Element& element,
                                                  const String& property,
                                                  const String& pseudo);
  static std::optional<String> QueryInnerText(const Element& element);
  static std::optional<Element*> QueryElementFromPoint(const TreeScope& scope,
                                                       double x,
                                                       double y);
  static std::optional<HeapVector<Member<Element>>>
  QueryElementsFromPoint(const TreeScope& scope, double x, double y);
  // Input event hit testing. Returns false (leaving `result` untouched) if
  // `document` has no render thread.
  // MouseEvent::ComputeRelativePosition on the render thread. Returns false
  // (leaving the points untouched) if `target` has no render thread.
  static bool QueryMouseRelativePosition(const Node& target,
                                         const gfx::PointF& absolute_location,
                                         float zoom_factor,
                                         gfx::PointF& offset,
                                         gfx::PointF& layer_location);
  static std::optional<Vector<gfx::RectF>> QueryRangeRects(
      const Range& range,
      RenderThreadQuery::Type type);
  static bool HitTest(Document& document,
                      const HitTestLocation& location,
                      HitTestResult& result);

  // BeginMainFrame on the main thread. Pushes the viewport to the render
  // thread and returns the layer that shows the render thread's output.
  cc::Layer* PrepareMainFrame(const LocalFrameView& view);
  PaintControllerPersistentData& PaintData();

  // WebSurfaceLayerBridgeObserver:
  void OnWebLayerUpdated() override;
  void RegisterContentsLayer(cc::Layer*) override {}
  void UnregisterContentsLayer(cc::Layer*) override {}

  // DisplayItemClient:
  String DebugName() const override { return "RenderThreadJournal"; }

  void Trace(Visitor* visitor) const override;

 private:
  class CommitObserver;

  // Returns false if `node` is not replicated by an active journal.
  static bool RunQuery(const Node& node, RenderThreadQuery& query);
  Element* ElementForId(uint32_t id) const;
  Node* NodeForId(uint32_t id) const;

  uint32_t IdOf(const Node& node) const;
  uint32_t AssignId(const Node& node);
  bool IsJournaledContainer(const ContainerNode& container) const;
  // Serializes a node and its subtree. Returns 0 if the node is not
  // replicated.
  uint32_t Serialize(const Node& node);
  void SerializeChildren(const ContainerNode& container, uint32_t container_id);
  void SerializeElement(const Element& element, uint32_t id);
  void ForgetSubtree(const Node& node);
  void Reconcile(const ContainerNode& container);
  uint32_t NextKnownSiblingId(const Node* from) const;
  bool ShouldSkipAttribute(const Element& element,
                           const QualifiedName& name) const;
  void SendSheetText(const Element& owner, uint32_t id);
  void Push(RenderThreadOp op);
  void SendViewport(const gfx::Size& size, float zoom);

  Member<Document> document_;
  scoped_refptr<RenderThreadChannel> channel_;
  std::unique_ptr<RenderThread> render_thread_;
  uint32_t next_id_ = 2;
  HeapHashMap<WeakMember<const Node>, uint32_t> ids_;
  HeapHashMap<uint32_t, WeakMember<const Node>> nodes_by_id_;
  // Elements whose children are not replicated (<script>, <noscript>).
  HeapHashSet<WeakMember<const Element>> opaque_;
  // <link rel=stylesheet> elements, replicated as <style>.
  HeapHashSet<WeakMember<const Element>> converted_links_;
  std::unique_ptr<CommitObserver> commit_observer_;
  std::unique_ptr<SurfaceLayerBridge> bridge_;
  Member<PaintControllerPersistentData> paint_data_;
  gfx::Size viewport_size_;
  float viewport_zoom_ = 0;
  bool detached_ = false;
  uint64_t main_thread_rendering_count_ = 0;
};

// Presents the render thread's output from the main thread's BeginMainFrame.
// Friend of LocalFrameView.
class CORE_EXPORT RenderThreadPresenter {
  STATIC_ONLY(RenderThreadPresenter);

 public:
  // Returns true if the main frame update was handled.
  static bool UpdateMainFrame(LocalFrameView& view);
};

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_JOURNAL_H_
