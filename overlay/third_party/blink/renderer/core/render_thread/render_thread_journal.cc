// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/core/render_thread/render_thread_journal.h"

#include "base/debug/stack_trace.h"
#include "base/functional/callback_helpers.h"
#include "base/logging.h"
#include "base/trace_event/trace_event.h"
#include "cc/layers/layer.h"
#include "cc/view_transition/view_transition_request.h"
#include "third_party/blink/renderer/core/css/css_import_rule.h"
#include "third_party/blink/renderer/core/css/css_property_value_set.h"
#include "third_party/blink/renderer/core/css/css_rule.h"
#include "third_party/blink/renderer/core/css/css_style_sheet.h"
#include "third_party/blink/renderer/core/css/media_list.h"
#include "third_party/blink/renderer/core/dom/character_data.h"
#include "third_party/blink/renderer/core/dom/document.h"
#include "third_party/blink/renderer/core/dom/document_type.h"
#include "third_party/blink/renderer/core/dom/element.h"
#include "third_party/blink/renderer/core/dom/range.h"
#include "third_party/blink/renderer/core/dom/shadow_root.h"
#include "third_party/blink/renderer/core/dom/tree_scope.h"
#include "third_party/blink/renderer/core/frame/local_frame.h"
#include "third_party/blink/renderer/core/frame/local_frame_view.h"
#include "third_party/blink/renderer/core/frame/settings.h"
#include "third_party/blink/renderer/core/html/forms/html_input_element.h"
#include "third_party/blink/renderer/core/html/html_link_element.h"
#include "third_party/blink/renderer/core/html_names.h"
#include "third_party/blink/renderer/core/layout/hit_test_location.h"
#include "third_party/blink/renderer/core/layout/hit_test_result.h"
#include "third_party/blink/renderer/core/page/chrome_client.h"
#include "third_party/blink/renderer/core/page/page.h"
#include "third_party/blink/renderer/core/page/scrolling/scrolling_coordinator.h"
#include "third_party/blink/renderer/core/render_thread/render_thread.h"
#include "third_party/blink/renderer/platform/graphics/compositing/paint_artifact_compositor.h"
#include "third_party/blink/renderer/platform/graphics/graphics_context.h"
#include "third_party/blink/renderer/platform/graphics/paint/foreign_layer_display_item.h"
#include "third_party/blink/renderer/platform/graphics/paint/paint_controller.h"
#include "third_party/blink/renderer/platform/graphics/paint/property_tree_state.h"
#include "third_party/blink/renderer/platform/graphics/surface_layer_bridge.h"
#include "third_party/blink/renderer/platform/runtime_enabled_features.h"
#include "third_party/blink/renderer/platform/scheduler/public/thread.h"
#include "third_party/blink/renderer/platform/wtf/text/string_builder.h"

namespace blink {

namespace {

bool IsStyleSheetLink(const Element& element) {
  const auto* link = DynamicTo<HTMLLinkElement>(element);
  return link && link->RelAttribute().IsStyleSheet();
}

// Appends the text of `sheet` (and of any loaded @import sheets, inlined) to
// `builder`. The replica cannot load resources, so imports are inlined.
void AppendSheetText(CSSStyleSheet& sheet,
                     ExecutionContext* context,
                     StringBuilder& builder,
                     int depth) {
  if (depth > 16) {
    return;
  }
  const unsigned length = sheet.length();
  for (unsigned i = 0; i < length; ++i) {
    CSSRule* rule = sheet.ItemInternal(i);
    if (!rule) {
      continue;
    }
    if (auto* import_rule = DynamicTo<CSSImportRule>(rule)) {
      CSSStyleSheet* imported = import_rule->styleSheet();
      if (!imported) {
        continue;
      }
      String media;
      if (MediaList* list = import_rule->media()) {
        media = list->mediaText(context);
      }
      if (!media.empty()) {
        builder.Append("@media ");
        builder.Append(media);
        builder.Append(" {\n");
      }
      AppendSheetText(*imported, context, builder, depth + 1);
      if (!media.empty()) {
        builder.Append("}\n");
      }
      continue;
    }
    builder.Append(rule->cssText());
    builder.Append('\n');
  }
}

}  // namespace

class RenderThreadJournal::CommitObserver final : public Thread::TaskObserver {
 public:
  explicit CommitObserver(RenderThreadJournal* journal) : journal_(journal) {}

  void WillProcessTask(const base::PendingTask&, bool) override {}
  void DidProcessTask(const base::PendingTask&) override {
    if (journal_) {
      journal_->CommitTask();
    }
  }

 private:
  WeakPersistent<RenderThreadJournal> journal_;
};

// static
void RenderThreadJournal::MaybeAttach(Document& document) {
  if (!RuntimeEnabledFeatures::OffMainThreadRenderingEnabled()) {
    return;
  }
  LocalFrame* frame = document.GetFrame();
  if (!frame || !frame->IsOutermostMainFrame() ||
      document.IsInitialEmptyDocument() || !document.IsHTMLDocument() ||
      !frame->GetWidgetForLocalRoot() || !document.GetPage()) {
    return;
  }
  const KURL& url = document.Url();
  if (!url.ProtocolIsInHttpFamily() && !url.ProtocolIs("file")) {
    return;
  }
  if (!frame->GetSettings() ||
      !frame->GetSettings()->GetAcceleratedCompositingEnabled()) {
    return;
  }
  document.SetRenderThreadJournal(
      MakeGarbageCollected<RenderThreadJournal>(document));
}

RenderThreadJournal::RenderThreadJournal(Document& document)
    : document_(document),
      channel_(base::MakeRefCounted<RenderThreadChannel>()) {
  LocalFrame* frame = document.GetFrame();
  Page* page = document.GetPage();

  bridge_ = std::make_unique<SurfaceLayerBridge>(
      page->GetChromeClient().GetFrameSinkId(frame), this,
      base::NullCallback());
  bridge_->CreateSolidColorLayer();
  bridge_->SetContentsOpaque(true);

  auto params = std::make_unique<RenderThreadReplicaParams>();
  params->channel = channel_;
  params->settings = std::make_unique<Settings>();
  RenderThread::CopySettings(*params->settings, page->GetSettings());
  params->screen_infos = page->GetChromeClient().GetScreenInfos(*frame);
  params->color_maps = page->GetColorProviderColorMaps();
  params->url = document.Url();
  params->frame_sink_id = bridge_->GetFrameSinkId();
  render_thread_ = std::make_unique<RenderThread>(std::move(params));

  ids_.Set(&document, 1u);
  nodes_by_id_.Set(1u, &document);
  CompatibilityModeChanged();
  if (LocalFrameView* view = frame->View()) {
    SendViewport(view->Size(), frame->LayoutZoomFactor());
  }

  // Replicate any existing DOM (a page restored from the back/forward cache).
  SerializeChildren(document, 1u);

  commit_observer_ = std::make_unique<CommitObserver>(this);
  Thread::Current()->AddTaskObserver(commit_observer_.get());
  LOG(INFO) << "[OMT] render thread journal attached to " << document.Url();
}

RenderThreadJournal::~RenderThreadJournal() = default;

// static
void RenderThreadJournal::SetInBackForwardCache(Document& document,
                                                bool in_cache) {
  if (in_cache) {
    if (RenderThreadJournal* journal = document.GetRenderThreadJournal()) {
      journal->Detach();
      document.SetRenderThreadJournal(nullptr);
      LOG(INFO) << "[OMT] page entered the back/forward cache; render thread "
                   "stopped";
    }
    return;
  }
  if (!document.GetRenderThreadJournal() && document.IsActive()) {
    MaybeAttach(document);
  }
}

void RenderThreadJournal::Detach() {
  if (detached_) {
    return;
  }
  detached_ = true;
  if (commit_observer_) {
    Thread::Current()->RemoveTaskObserver(commit_observer_.get());
    commit_observer_.reset();
  }
  // Stops the page's render thread; its replica is destroyed on it.
  render_thread_.reset();
  if (bridge_) {
    bridge_->ClearObserver();
    bridge_.reset();
  }
  ids_.clear();
  nodes_by_id_.clear();
}

void RenderThreadJournal::Trace(Visitor* visitor) const {
  visitor->Trace(document_);
  visitor->Trace(ids_);
  visitor->Trace(nodes_by_id_);
  visitor->Trace(opaque_);
  visitor->Trace(converted_links_);
  visitor->Trace(paint_data_);
  DisplayItemClient::Trace(visitor);
}

void RenderThreadJournal::Push(RenderThreadOp op) {
  if (detached_) {
    return;
  }
  if (channel_->Push(std::move(op)) && channel_->MarkWakePending()) {
    render_thread_->Wake();
  }
}

void RenderThreadJournal::CommitTask() {
  if (detached_) {
    return;
  }
  if (channel_->Commit() && channel_->MarkWakePending()) {
    render_thread_->Wake();
  }
}

namespace {
constinit thread_local int g_focus_scope_depth = 0;
}  // namespace

RenderThreadJournal::FocusScope::FocusScope() {
  ++g_focus_scope_depth;
}

RenderThreadJournal::FocusScope::~FocusScope() {
  --g_focus_scope_depth;
}

bool RenderThreadJournal::NoteMainThreadRendering(const char* phase,
                                                  int reason) {
  if (detached_) {
    return true;
  }
  if (g_focus_scope_depth) {
    TRACE_EVENT_INSTANT("blink", "RenderThreadJournal::SkippedForFocus",
                        "phase", phase, "reason", reason);
    return false;
  }
  const uint64_t count = ++main_thread_rendering_count_;
  // Unthrottled, so tooling can prove the absence of main-thread rendering.
  TRACE_EVENT_INSTANT("blink", "RenderThreadJournal::MainThreadFallback",
                      "phase", phase, "reason", reason, "count", count);
  if (count <= 10 || count % 100 == 0) {
    LOG(INFO) << "[OMT] main-thread " << phase << " fallback #" << count
              << " (reason " << reason << ")";
    if (count <= 3) {
      LOG(INFO) << "[OMT] fallback stack:\n" << base::debug::StackTrace(14);
    }
  }
  return true;
}

uint32_t RenderThreadJournal::IdOf(const Node& node) const {
  auto it = ids_.find(&node);
  return it == ids_.end() ? 0u : it->value;
}

uint32_t RenderThreadJournal::AssignId(const Node& node) {
  uint32_t id = next_id_++;
  ids_.Set(&node, id);
  nodes_by_id_.Set(id, &node);
  return id;
}

Node* RenderThreadJournal::NodeForId(uint32_t id) const {
  if (!id) {
    return nullptr;
  }
  auto it = nodes_by_id_.find(id);
  if (it == nodes_by_id_.end()) {
    return nullptr;
  }
  return const_cast<Node*>(it->value.Get());
}

Element* RenderThreadJournal::ElementForId(uint32_t id) const {
  return DynamicTo<Element>(NodeForId(id));
}

// static
bool RenderThreadJournal::QueryMouseRelativePosition(
    const Node& target,
    const gfx::PointF& absolute_location,
    float zoom_factor,
    gfx::PointF& offset,
    gfx::PointF& layer_location) {
  RenderThreadQuery query{
      .type = RenderThreadQuery::Type::kMouseRelativePosition,
      .x = absolute_location.x(),
      .y = absolute_location.y(),
      .number = zoom_factor,
      .rects = {gfx::RectF(offset, gfx::SizeF()),
                gfx::RectF(layer_location, gfx::SizeF())}};
  if (!RunQuery(target, query) || query.rects.size() != 2) {
    return false;
  }
  offset = query.rects[0].origin();
  layer_location = query.rects[1].origin();
  return true;
}

// static
std::optional<Vector<gfx::RectF>> RenderThreadJournal::QueryRangeRects(
    const Range& range,
    RenderThreadQuery::Type type) {
  RenderThreadJournal* journal = range.OwnerDocument().GetRenderThreadJournal();
  if (!journal) {
    return std::nullopt;
  }
  RenderThreadQuery query{.type = type,
                          .node2 = journal->IdOf(*range.endContainer()),
                          .x = static_cast<double>(range.startOffset()),
                          .y = static_cast<double>(range.endOffset())};
  if (!query.node2 || !RunQuery(*range.startContainer(), query)) {
    return std::nullopt;
  }
  return std::move(query.rects);
}

// static
bool RenderThreadJournal::HitTest(Document& document,
                                  const HitTestLocation& location,
                                  HitTestResult& result) {
  if (location.IsRectBasedTest()) {
    return false;
  }
  const gfx::PointF point(location.Point());
  RenderThreadQuery query{.type = RenderThreadQuery::Type::kHitTest,
                          .x = point.x(),
                          .y = point.y()};
  if (!RunQuery(document, query)) {
    return false;
  }
  if (Node* node =
          document.GetRenderThreadJournal()->NodeForId(query.result_node)) {
    result.SetNodeAndPosition(node, PhysicalOffset::FromPointFRound(gfx::PointF(
                                        query.result_x, query.result_y)));
    result.SetURLElement(node->EnclosingLinkEventParentOrSelf());
  }
  return true;
}

// static
bool RenderThreadJournal::RunQuery(const Node& node, RenderThreadQuery& query) {
  RenderThreadJournal* journal = node.GetDocument().GetRenderThreadJournal();
  if (!journal || journal->detached_ || !journal->render_thread_) {
    return false;
  }
  query.node = journal->IdOf(node);
  if (!query.node) {
    return false;
  }
  // The viewport may have been resized since the last frame (for example,
  // script in a resize event handler runs before the next frame is prepared).
  if (LocalFrameView* view = journal->document_->View()) {
    journal->SendViewport(view->Size(), view->GetFrame().LayoutZoomFactor());
  }
  // Everything the script did so far must be visible to the query.
  journal->channel_->Commit();
  journal->render_thread_->RunQuery(query);
  return query.answered;
}

// static
std::optional<double> RenderThreadJournal::QueryNumber(
    const Element& element,
    RenderThreadQuery::Type type) {
  RenderThreadQuery query{.type = type};
  if (!RunQuery(element, query)) {
    return std::nullopt;
  }
  return query.number;
}

// static
std::optional<double> RenderThreadJournal::QueryWindowNumber(
    const Document& document,
    RenderThreadQuery::Type type) {
  RenderThreadQuery query{.type = type};
  if (!RunQuery(document, query)) {
    return std::nullopt;
  }
  return query.number;
}

// static
std::optional<Element*> RenderThreadJournal::QueryOffsetParent(
    const Element& element) {
  RenderThreadQuery query{.type = RenderThreadQuery::Type::kOffsetParent};
  if (!RunQuery(element, query)) {
    return std::nullopt;
  }
  return element.GetDocument().GetRenderThreadJournal()->ElementForId(
      query.result_node);
}

// static
std::optional<Vector<gfx::RectF>> RenderThreadJournal::QueryRects(
    const Element& element,
    RenderThreadQuery::Type type) {
  RenderThreadQuery query{.type = type};
  if (!RunQuery(element, query)) {
    return std::nullopt;
  }
  return std::move(query.rects);
}

// static
std::optional<String> RenderThreadJournal::QueryComputedStyle(
    const Element& element,
    const String& property,
    const String& pseudo) {
  RenderThreadQuery query{.type = RenderThreadQuery::Type::kComputedStyle,
                          .text = property,
                          .pseudo = pseudo};
  if (!RunQuery(element, query)) {
    return std::nullopt;
  }
  return query.text;
}

// static
std::optional<String> RenderThreadJournal::QueryInnerText(
    const Element& element) {
  RenderThreadQuery query{.type = RenderThreadQuery::Type::kInnerText};
  if (!RunQuery(element, query)) {
    return std::nullopt;
  }
  return query.text;
}

// static
std::optional<Element*> RenderThreadJournal::QueryElementFromPoint(
    const TreeScope& scope,
    double x,
    double y) {
  RenderThreadQuery query{
      .type = RenderThreadQuery::Type::kElementFromPoint, .x = x, .y = y};
  if (!RunQuery(scope.RootNode(), query)) {
    return std::nullopt;
  }
  return scope.GetDocument().GetRenderThreadJournal()->ElementForId(
      query.result_node);
}

// static
std::optional<HeapVector<Member<Element>>>
RenderThreadJournal::QueryElementsFromPoint(const TreeScope& scope,
                                            double x,
                                            double y) {
  RenderThreadQuery query{
      .type = RenderThreadQuery::Type::kElementsFromPoint, .x = x, .y = y};
  if (!RunQuery(scope.RootNode(), query)) {
    return std::nullopt;
  }
  RenderThreadJournal* journal = scope.GetDocument().GetRenderThreadJournal();
  HeapVector<Member<Element>> elements;
  for (uint32_t id : query.result_nodes) {
    if (Element* element = journal->ElementForId(id)) {
      elements.push_back(element);
    }
  }
  return elements;
}

bool RenderThreadJournal::IsJournaledContainer(
    const ContainerNode& container) const {
  if (detached_ || !IdOf(container)) {
    return false;
  }
  if (const auto* element = DynamicTo<Element>(container)) {
    return !opaque_.Contains(element) && !converted_links_.Contains(element);
  }
  return true;
}

bool RenderThreadJournal::ShouldSkipAttribute(const Element& element,
                                              const QualifiedName& name) const {
  // The replica never loads subresources, runs script or navigates.
  if (element.HasTagName(html_names::kScriptTag)) {
    return name == html_names::kSrcAttr;
  }
  if (element.HasTagName(html_names::kImgTag) ||
      element.HasTagName(html_names::kSourceTag) ||
      element.HasTagName(html_names::kVideoTag) ||
      element.HasTagName(html_names::kAudioTag) ||
      element.HasTagName(html_names::kTrackTag) ||
      element.HasTagName(html_names::kInputTag) ||
      element.HasTagName(html_names::kIFrameTag) ||
      element.HasTagName(html_names::kFrameTag) ||
      element.HasTagName(html_names::kEmbedTag) ||
      element.HasTagName(html_names::kObjectTag)) {
    return name == html_names::kSrcAttr || name == html_names::kSrcsetAttr ||
           name == html_names::kPosterAttr || name == html_names::kDataAttr ||
           name == html_names::kSrcdocAttr;
  }
  if (element.HasTagName(html_names::kLinkTag)) {
    return name == html_names::kHrefAttr;
  }
  if (element.HasTagName(html_names::kMetaTag)) {
    return name == html_names::kHttpEquivAttr;
  }
  return false;
}

uint32_t RenderThreadJournal::Serialize(const Node& node) {
  if (IdOf(node)) {
    return IdOf(node);
  }
  switch (node.getNodeType()) {
    case Node::kElementNode: {
      uint32_t id = AssignId(node);
      SerializeElement(To<Element>(node), id);
      return id;
    }
    case Node::kTextNode:
    case Node::kCdataSectionNode: {
      uint32_t id = AssignId(node);
      RenderThreadOp op{.type = RenderThreadOp::Type::kCreateText, .node = id};
      op.text = To<CharacterData>(node).data();
      Push(std::move(op));
      return id;
    }
    case Node::kCommentNode: {
      uint32_t id = AssignId(node);
      RenderThreadOp op{.type = RenderThreadOp::Type::kCreateComment,
                        .node = id};
      op.text = To<CharacterData>(node).data();
      Push(std::move(op));
      return id;
    }
    case Node::kDocumentTypeNode: {
      const auto& doctype = To<DocumentType>(node);
      uint32_t id = AssignId(node);
      RenderThreadOp op{.type = RenderThreadOp::Type::kCreateDoctype,
                        .node = id};
      op.local_name = doctype.name();
      op.ns = doctype.publicId();
      op.prefix = doctype.systemId();
      Push(std::move(op));
      return id;
    }
    default:
      return 0;
  }
}

void RenderThreadJournal::SerializeElement(const Element& element,
                                           uint32_t id) {
  const bool is_style_link = IsStyleSheetLink(element);
  RenderThreadOp create{.type = RenderThreadOp::Type::kCreateElement,
                        .node = id};
  if (is_style_link) {
    // Replicated as <style>, with the loaded sheet text.
    create.ns = html_names::xhtmlNamespaceURI;
    create.local_name = html_names::kStyleTag.LocalName();
    converted_links_.insert(&element);
  } else {
    create.ns = element.namespaceURI();
    create.prefix = element.prefix();
    create.local_name = element.localName();
  }
  Push(std::move(create));

  for (const Attribute& attribute : element.AttributesWithoutUpdate()) {
    const QualifiedName& name = attribute.GetName();
    if (is_style_link ? name != html_names::kMediaAttr
                      : ShouldSkipAttribute(element, name)) {
      continue;
    }
    RenderThreadOp op{.type = RenderThreadOp::Type::kSetAttribute, .node = id};
    op.ns = name.NamespaceURI();
    op.prefix = name.Prefix();
    op.local_name = name.LocalName();
    op.text = attribute.Value();
    Push(std::move(op));
  }
  // Lazily synchronized style attribute.
  if (!is_style_link && element.InlineStyle()) {
    RenderThreadOp op{.type = RenderThreadOp::Type::kSetAttribute, .node = id};
    op.ns = g_null_atom;
    op.local_name = html_names::kStyleAttr.LocalName();
    op.text = element.InlineStyle()->AsText();
    Push(std::move(op));
  }

  if (element.IsHovered()) {
    Push({.type = RenderThreadOp::Type::kSetElementState,
          .node = id,
          .int_value =
              static_cast<int32_t>(RenderThreadOp::ElementState::kHovered),
          .int_value2 = 1});
  }
  if (element.IsFocused()) {
    Push({.type = RenderThreadOp::Type::kSetElementState,
          .node = id,
          .int_value =
              static_cast<int32_t>(RenderThreadOp::ElementState::kFocused),
          .int_value2 = 1});
  }
  if (const auto* input = DynamicTo<HTMLInputElement>(element)) {
    if (input->Checked() != input->FastHasAttribute(html_names::kCheckedAttr)) {
      Push({.type = RenderThreadOp::Type::kSetElementState,
            .node = id,
            .int_value =
                static_cast<int32_t>(RenderThreadOp::ElementState::kChecked),
            .int_value2 = input->Checked() ? 1 : 0});
    }
  }

  if (is_style_link) {
    SendSheetText(element, id);
    return;
  }
  if (element.HasTagName(html_names::kScriptTag)) {
    opaque_.insert(&element);
    return;
  }
  if (element.HasTagName(html_names::kNoscriptTag)) {
    // Script runs on the main thread, so <noscript> content never renders.
    // The replica has scripting disabled, so hide it explicitly.
    opaque_.insert(&element);
    RenderThreadOp op{.type = RenderThreadOp::Type::kSetAttribute, .node = id};
    op.ns = g_null_atom;
    op.local_name = html_names::kHiddenAttr.LocalName();
    op.text = g_empty_atom;
    Push(std::move(op));
    return;
  }

  if (ShadowRoot* root = element.GetShadowRoot();
      root && !root->IsUserAgent()) {
    ShadowRootAttached(element, *root);
  }
  SerializeChildren(element, id);
}

void RenderThreadJournal::SerializeChildren(const ContainerNode& container,
                                            uint32_t container_id) {
  for (Node* child = container.firstChild(); child;
       child = child->nextSibling()) {
    if (IdOf(*child)) {
      continue;
    }
    if (uint32_t child_id = Serialize(*child)) {
      Push({.type = RenderThreadOp::Type::kInsert,
            .node = child_id,
            .parent = container_id});
    }
  }
}

void RenderThreadJournal::ShadowRootAttached(const Element& host,
                                             ShadowRoot& root) {
  uint32_t host_id = IdOf(host);
  if (!host_id || root.IsUserAgent() || IdOf(root) || detached_) {
    return;
  }
  uint32_t id = AssignId(root);
  int flags =
      (root.delegatesFocus() ? 1 : 0) | (root.IsManualSlotting() ? 2 : 0);
  Push({.type = RenderThreadOp::Type::kAttachShadowRoot,
        .node = id,
        .parent = host_id,
        .int_value = static_cast<int32_t>(root.GetMode()),
        .int_value2 = flags});
  SerializeChildren(root, id);
}

void RenderThreadJournal::ForgetSubtree(const Node& node) {
  if (uint32_t id = IdOf(node)) {
    nodes_by_id_.erase(id);
  }
  ids_.erase(&node);
  if (const auto* element = DynamicTo<Element>(node)) {
    if (ShadowRoot* root = element->GetShadowRoot()) {
      ForgetSubtree(*root);
    }
  }
  if (const auto* container = DynamicTo<ContainerNode>(node)) {
    for (Node* child = container->firstChild(); child;
         child = child->nextSibling()) {
      ForgetSubtree(*child);
    }
  }
}

uint32_t RenderThreadJournal::NextKnownSiblingId(const Node* from) const {
  for (const Node* sibling = from; sibling; sibling = sibling->nextSibling()) {
    if (uint32_t id = IdOf(*sibling)) {
      return id;
    }
  }
  return 0;
}

void RenderThreadJournal::Reconcile(const ContainerNode& container) {
  if (!IsJournaledContainer(container)) {
    return;
  }
  const uint32_t container_id = IdOf(container);
  uint32_t before = 0;
  for (Node* child = container.lastChild(); child;
       child = child->previousSibling()) {
    if (uint32_t id = IdOf(*child)) {
      before = id;
      if (auto* child_container = DynamicTo<ContainerNode>(child)) {
        Reconcile(*child_container);
      }
      continue;
    }
    if (uint32_t id = Serialize(*child)) {
      Push({.type = RenderThreadOp::Type::kInsert,
            .node = id,
            .parent = container_id,
            .before = before});
      before = id;
    }
  }
}

void RenderThreadJournal::ChildrenChanged(
    const ContainerNode& container,
    const ContainerNode::ChildrenChange& change) {
  if (!IsJournaledContainer(container)) {
    return;
  }
  const uint32_t container_id = IdOf(container);
  using Type = ContainerNode::ChildrenChangeType;
  switch (change.type) {
    case Type::kElementInserted:
    case Type::kNonElementInserted: {
      Node* first = change.sibling_before_change
                        ? change.sibling_before_change->nextSibling()
                        : container.firstChild();
      Node* end = change.sibling_after_change;
      if (first && first->parentNode() != &container) {
        Reconcile(container);
        return;
      }
      const uint32_t before = NextKnownSiblingId(end);
      for (Node* node = first; node && node != end;
           node = node->nextSibling()) {
        if (IdOf(*node)) {
          continue;
        }
        if (uint32_t id = Serialize(*node)) {
          Push({.type = RenderThreadOp::Type::kInsert,
                .node = id,
                .parent = container_id,
                .before = before});
        }
      }
      return;
    }
    case Type::kElementRemoved:
    case Type::kNonElementRemoved: {
      if (!change.sibling_changed) {
        return;
      }
      if (uint32_t id = IdOf(*change.sibling_changed)) {
        Push({.type = RenderThreadOp::Type::kRemove, .node = id});
        ForgetSubtree(*change.sibling_changed);
      }
      return;
    }
    case Type::kAllChildrenRemoved: {
      Push({.type = RenderThreadOp::Type::kRemoveAllChildren,
            .parent = container_id});
      for (const auto& node : change.removed_nodes) {
        ForgetSubtree(*node);
      }
      return;
    }
    case Type::kTextChanged: {
      const auto* data = DynamicTo<CharacterData>(change.sibling_changed);
      if (!data) {
        return;
      }
      if (uint32_t id = IdOf(*data)) {
        RenderThreadOp op{.type = RenderThreadOp::Type::kSetText, .node = id};
        op.text = data->data();
        Push(std::move(op));
      }
      return;
    }
    case Type::kFinishedBuildingDocumentFragmentTree:
      Reconcile(container);
      return;
  }
}

void RenderThreadJournal::AttributeChanged(const Element& element,
                                           const QualifiedName& name,
                                           const AtomicString& new_value) {
  if (detached_) {
    return;
  }
  const uint32_t id = IdOf(element);
  if (!id) {
    return;
  }
  if (converted_links_.Contains(&element)) {
    if (name != html_names::kMediaAttr) {
      return;
    }
  } else if (ShouldSkipAttribute(element, name)) {
    return;
  }
  RenderThreadOp op{.type = new_value.IsNull()
                                ? RenderThreadOp::Type::kRemoveAttribute
                                : RenderThreadOp::Type::kSetAttribute,
                    .node = id};
  op.ns = name.NamespaceURI();
  op.prefix = name.Prefix();
  op.local_name = name.LocalName();
  op.text = new_value;
  Push(std::move(op));
}

void RenderThreadJournal::InlineStyleChanged(const Element& element) {
  const uint32_t id = IdOf(element);
  if (!id || detached_ || converted_links_.Contains(&element)) {
    return;
  }
  RenderThreadOp op{.type = RenderThreadOp::Type::kSetAttribute, .node = id};
  op.ns = g_null_atom;
  op.local_name = html_names::kStyleAttr.LocalName();
  op.text =
      element.InlineStyle() ? element.InlineStyle()->AsText() : g_empty_string;
  Push(std::move(op));
}

// static
bool RenderThreadJournal::Scroll(const Node& element,
                                 std::optional<double> left,
                                 std::optional<double> top,
                                 bool relative) {
  RenderThreadJournal* journal = element.GetDocument().GetRenderThreadJournal();
  if (!journal || journal->detached_ || !journal->render_thread_) {
    return false;
  }
  const uint32_t id = journal->IdOf(element);
  if (!id) {
    return false;
  }
  journal->Push(
      {.type = RenderThreadOp::Type::kScrollElement,
       .node = id,
       .int_value = (left ? 1 : 0) | (top ? 2 : 0) | (relative ? 4 : 0),
       .float_value = static_cast<float>(left.value_or(0)),
       .float_value2 = static_cast<float>(top.value_or(0))});
  return true;
}

void RenderThreadJournal::ElementStateChanged(
    const Element& element,
    RenderThreadOp::ElementState state,
    bool value) {
  const uint32_t id = IdOf(element);
  if (!id || detached_) {
    return;
  }
  Push({.type = RenderThreadOp::Type::kSetElementState,
        .node = id,
        .int_value = static_cast<int32_t>(state),
        .int_value2 = value ? 1 : 0});
}

void RenderThreadJournal::SendSheetText(const Element& owner, uint32_t id) {
  CSSStyleSheet* sheet = nullptr;
  // <style> elements are serialized with their text. Only linked sheets and
  // CSSOM mutations (see StyleSheetChanged()) need their rules sent.
  if (const auto* link = DynamicTo<HTMLLinkElement>(owner)) {
    sheet = link->sheet();
  }
  if (!sheet) {
    return;
  }
  StringBuilder builder;
  AppendSheetText(*sheet, document_->GetExecutionContext(), builder, 0);
  RenderThreadOp op{.type = RenderThreadOp::Type::kSetSheetText, .node = id};
  op.text = builder.ReleaseString();
  Push(std::move(op));
}

void RenderThreadJournal::StyleSheetChanged(const CSSStyleSheet& sheet) {
  if (detached_) {
    return;
  }
  const auto* owner = DynamicTo<Element>(sheet.ownerNode());
  if (!owner) {
    return;
  }
  const uint32_t id = IdOf(*owner);
  if (!id) {
    return;
  }
  StringBuilder builder;
  AppendSheetText(const_cast<CSSStyleSheet&>(sheet),
                  document_->GetExecutionContext(), builder, 0);
  RenderThreadOp op{.type = RenderThreadOp::Type::kSetSheetText, .node = id};
  op.text = builder.ReleaseString();
  Push(std::move(op));
}

void RenderThreadJournal::CompatibilityModeChanged() {
  Push({.type = RenderThreadOp::Type::kSetCompatMode,
        .int_value = static_cast<int32_t>(document_->GetCompatibilityMode())});
}

void RenderThreadJournal::SendViewport(const gfx::Size& size, float zoom) {
  if (size == viewport_size_ && zoom == viewport_zoom_) {
    return;
  }
  viewport_size_ = size;
  viewport_zoom_ = zoom;
  Push({.type = RenderThreadOp::Type::kSetViewport,
        .int_value = size.width(),
        .int_value2 = size.height(),
        .float_value = zoom});
  // Resizes should show up without waiting for the end of the task.
  CommitTask();
}

cc::Layer* RenderThreadJournal::PrepareMainFrame(const LocalFrameView& view) {
  if (detached_ || !bridge_) {
    return nullptr;
  }
  SendViewport(view.Size(), view.GetFrame().LayoutZoomFactor());
  cc::Layer* layer = bridge_->GetCcLayer();
  if (layer) {
    layer->SetBounds(view.Size());
    layer->SetIsDrawable(true);
  }
  return layer;
}

PaintControllerPersistentData& RenderThreadJournal::PaintData() {
  if (!paint_data_) {
    paint_data_ = MakeGarbageCollected<PaintControllerPersistentData>();
  }
  return *paint_data_;
}

void RenderThreadJournal::OnWebLayerUpdated() {
  if (!detached_ && document_->View()) {
    document_->View()->ScheduleAnimation();
  }
}

// static
bool RenderThreadPresenter::UpdateMainFrame(LocalFrameView& view) {
  Document* document = view.GetFrame().GetDocument();
  RenderThreadJournal* journal =
      document ? document->GetRenderThreadJournal() : nullptr;
  if (!journal) {
    return false;
  }
  Page* page = view.GetFrame().GetPage();
  if (!page) {
    return false;
  }
  cc::Layer* layer = journal->PrepareMainFrame(view);
  if (!layer) {
    return false;
  }

  if (!view.paint_artifact_compositor_) {
    view.paint_artifact_compositor_ =
        MakeGarbageCollected<PaintArtifactCompositor>(
            page->GetScrollingCoordinator()->GetScrollCallbacks());
    page->GetChromeClient().AttachRootLayer(
        view.paint_artifact_compositor_->RootLayer(), &view.GetFrame());
  }

  PaintControllerPersistentData& data = journal->PaintData();
  const PropertyTreeState root_state = PropertyTreeState::Root();
  // The compositor update must happen while the PaintController is alive:
  // destroying it clears the previous artifact, which the compositor's old
  // pending layers still reference for layer matching.
  PaintController paint_controller(/*record_debug_info=*/false, &data);
  {
    GraphicsContext context(paint_controller);
    RecordForeignLayer(context, *journal, DisplayItem::kForeignLayerCanvas,
                       layer, gfx::Point(), &root_state);
  }
  paint_controller.CommitNewDisplayItems();

  PaintArtifactCompositor& compositor = *view.paint_artifact_compositor_;
  compositor.SetDevicePixelRatio(document->DevicePixelRatio());
  compositor.SetNeedsUpdate();
  compositor.Update(data.GetPaintArtifact(),
                    PaintArtifactCompositor::ViewportProperties(),
                    StackTransformPaintPropertyNodeVector(),
                    Vector<std::unique_ptr<cc::ViewTransitionRequest>>());
  return true;
}

}  // namespace blink
