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
#include "third_party/blink/renderer/platform/wtf/hash_map.h"
#include "ui/gfx/geometry/point_f.h"
#include "ui/gfx/geometry/size.h"

namespace cc {
class Layer;
}

namespace blink {

class CSSStyleSheet;
class Document;
class Element;
class GraphicsContext;
class HitTestLocation;
class HTMLImageElement;
class ImageResourceContent;
class HitTestResult;
class Range;
class LocalFrameView;
class QualifiedName;
class RenderThread;
class ShadowRoot;
class SurfaceLayerBridge;
class TreeScope;

// Off-main-thread rendering (--enable-blink-features=OffMainThreadRendering).
//
// The main thread renders the page exactly as without this feature. Every
// change to the DOM that can affect rendering is also recorded here as a
// RenderThreadOp and sent to the page's render thread (see render_thread.h),
// which keeps a replica of the document with up-to-date style.
//
// When a main-thread task runs for longer than a few frames while the page is
// changing (a CSS transition is running, or the task mutated the DOM), the
// render thread takes over: it lays out, paints and presents the replica on
// its own, and the main thread's layout queries are answered by it. When the
// task ends, the main thread takes rendering back, adopting the replica's
// animation timing, and the render thread goes back to only following the
// DOM. See RenderThreadChannel::Mode.
//
// The main thread's frames always contain the render thread's output surface
// as the topmost layer; it is transparent unless the render thread renders.
//
// One journal exists per outermost main frame document. Pages whose content
// the replica cannot reproduce (images, plugins, frames, form fields, web
// fonts, CSS resources) detach it and render as usual.
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

  // Main thread task boundaries.
  void WillProcessTask();
  void DidProcessTask();
  void CommitTask();

  // True while the render thread renders the page for the busy main thread.
  bool IsRendering() const;
  static bool IsRendering(const Document& document);

  // Entry of Document::UpdateStyleAndLayoutTree (`phase` "style") and
  // Document::UpdateStyleAndLayout ("layout"). While the render thread
  // renders, main-thread style or layout is a fallback: it is counted, traced
  // and logged, and false is returned if it should be skipped (see
  // FocusScope). Otherwise returns true.
  bool NoteMainThreadRendering(const char* phase, int reason);
  // End of Document::UpdateStyleAndLayoutTree.
  void DidUpdateStyle();
  // End of a BeginMainFrame lifecycle update.
  static void DidUpdateMainFrame(LocalFrameView& view);
  // Records the render thread's output surface as the topmost layer of the
  // main frame's paint.
  static void PaintOverlay(GraphicsContext& context,
                           const LocalFrameView& view);

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
  // While the render thread renders, these ask it and wait for its answer.
  // They return std::nullopt otherwise (or when the node is not replicated),
  // in which case the caller uses the regular main-thread path.
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

  // WebSurfaceLayerBridgeObserver:
  void OnWebLayerUpdated() override;
  void RegisterContentsLayer(cc::Layer*) override {}
  void UnregisterContentsLayer(cc::Layer*) override {}

  // DisplayItemClient:
  String DebugName() const override { return "RenderThreadJournal"; }

  void Trace(Visitor* visitor) const override;

 private:
  class CommitObserver;

  // Returns false if the render thread is not rendering or `node` is not
  // replicated.
  static bool RunQuery(const Node& node, RenderThreadQuery& query);
  // Sends `query` regardless of the rendering mode.
  bool SendQuery(const Node& node, RenderThreadQuery& query);

  // Rendering hand-off (see RenderThreadChannel::Mode).
  void BeginHandBack();
  void SyncAnimationTimings();
  void FinishHandBack();
  void SendScrollOffsets(const LocalFrameView& view);
  void UpdateTakeoverAllowed();
  // The replica cannot reproduce the page; stop the render thread at the end
  // of the current task and render on the main thread only.
  void MarkUnreplicable(const char* reason);
  void DetachUnreplicable();
  void CheckReplicable(const Element& element);
  void CheckReplicableStyle(const Element& owner, const String& css_text);
  void InvalidateOverlay();

  // The image last sent to the render thread for an <img>.
  class SentImage final : public GarbageCollected<SentImage> {
   public:
    void Trace(Visitor* visitor) const;
    // Null: sent as "not loaded yet".
    Member<ImageResourceContent> content;
    // 0: nothing sent yet.
    float device_pixel_ratio = 0;
  };
  // Sends the images of <img> elements that finished loading or changed.
  // The main thread loads and decodes them; the replica never loads.
  void SyncImages();
  void SyncImage(const HTMLImageElement& element, SentImage& sent);

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

  struct PendingScroll {
    uint32_t node;
    std::optional<double> left;
    std::optional<double> top;
    bool relative;
  };

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
  HeapHashMap<WeakMember<const HTMLImageElement>, Member<SentImage>> images_;
  std::unique_ptr<CommitObserver> commit_observer_;
  std::unique_ptr<SurfaceLayerBridge> bridge_;
  gfx::Size viewport_size_;
  float viewport_zoom_ = 0;
  bool detached_ = false;
  uint64_t main_thread_rendering_count_ = 0;
  // Journal entries pushed since the last kStyleSync.
  bool ops_since_style_sync_ = false;
  // A kStyleSync was sent since the last frame marker.
  bool style_sync_since_frame_ = false;
  // Outermost task nesting on the main thread.
  int task_depth_ = 0;
  // Hand-back state.
  bool needs_timing_sync_ = false;
  bool hand_back_presentation_requested_ = false;
  // Scrolls done by script while the render thread rendered; replayed on the
  // main thread when it takes rendering back.
  Vector<PendingScroll> pending_scrolls_;
  // Last scroll offsets sent to the render thread, by node id.
  HashMap<uint32_t, gfx::PointF> sent_scroll_offsets_;
  const char* unreplicable_reason_ = nullptr;
  uint64_t takeovers_ = 0;
};

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_JOURNAL_H_
