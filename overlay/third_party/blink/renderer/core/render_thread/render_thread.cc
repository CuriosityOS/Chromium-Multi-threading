// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/core/render_thread/render_thread.h"

#include <atomic>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/raw_ptr.h"
#include "base/synchronization/lock.h"
#include "base/synchronization/waitable_event.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/trace_event/trace_event.h"
#include "cc/paint/paint_recorder.h"
#include "components/viz/common/resources/shared_image_format.h"
#include "gpu/command_buffer/common/shared_image_usage.h"
#include "services/network/public/cpp/single_request_url_loader_factory.h"
#include "third_party/blink/public/common/tokens/tokens.h"
#include "third_party/blink/public/mojom/input/focus_type.mojom-blink.h"
#include "third_party/blink/renderer/core/animation/animation_clock.h"
#include "third_party/blink/renderer/core/animation/animation_effect.h"
#include "third_party/blink/renderer/core/animation/css/css_animation.h"
#include "third_party/blink/renderer/core/animation/css/css_transition.h"
#include "third_party/blink/renderer/core/animation/document_animations.h"
#include "third_party/blink/renderer/core/animation/document_timeline.h"
#include "third_party/blink/renderer/core/animation/pending_animations.h"
#include "third_party/blink/renderer/core/css/css_computed_style_declaration.h"
#include "third_party/blink/renderer/core/dom/character_data.h"
#include "third_party/blink/renderer/core/dom/comment.h"
#include "third_party/blink/renderer/core/dom/document.h"
#include "third_party/blink/renderer/core/dom/document_type.h"
#include "third_party/blink/renderer/core/dom/element.h"
#include "third_party/blink/renderer/core/dom/qualified_name.h"
#include "third_party/blink/renderer/core/dom/range.h"
#include "third_party/blink/renderer/core/dom/shadow_root.h"
#include "third_party/blink/renderer/core/dom/text.h"
#include "third_party/blink/renderer/core/events/mouse_event.h"
#include "third_party/blink/renderer/core/frame/local_dom_window.h"
#include "third_party/blink/renderer/core/frame/local_frame.h"
#include "third_party/blink/renderer/core/frame/local_frame_view.h"
#include "third_party/blink/renderer/core/frame/policy_container.h"
#include "third_party/blink/renderer/core/frame/settings.h"
#include "third_party/blink/renderer/core/frame/visual_viewport.h"
#include "third_party/blink/renderer/core/geometry/dom_rect.h"
#include "third_party/blink/renderer/core/geometry/dom_rect_list.h"
#include "third_party/blink/renderer/core/html/forms/html_input_element.h"
#include "third_party/blink/renderer/core/html/html_element.h"
#include "third_party/blink/renderer/core/layout/hit_test_location.h"
#include "third_party/blink/renderer/core/layout/hit_test_request.h"
#include "third_party/blink/renderer/core/layout/hit_test_result.h"
#include "third_party/blink/renderer/core/layout/layout_view.h"
#include "third_party/blink/renderer/core/loader/empty_clients.h"
#include "third_party/blink/renderer/core/page/focus_controller.h"
#include "third_party/blink/renderer/core/page/page.h"
#include "third_party/blink/renderer/core/page/page_animator.h"
#include "third_party/blink/renderer/core/workers/worker_backing_thread.h"
#include "third_party/blink/renderer/core/workers/worker_backing_thread_startup_data.h"
#include "third_party/blink/renderer/platform/bindings/exception_state.h"
#include "third_party/blink/renderer/platform/bindings/v8_per_isolate_data.h"
#include "third_party/blink/renderer/platform/graphics/canvas_2d_color_params.h"
#include "third_party/blink/renderer/platform/graphics/canvas_2d_resource_provider.h"
#include "third_party/blink/renderer/platform/graphics/canvas_resource.h"
#include "third_party/blink/renderer/platform/graphics/canvas_resource_dispatcher.h"
#include "third_party/blink/renderer/platform/graphics/exported_canvas_resource.h"
#include "third_party/blink/renderer/platform/graphics/gpu/shared_gpu_context.h"
#include "third_party/blink/renderer/platform/heap/collection_support/heap_hash_map.h"
#include "third_party/blink/renderer/platform/heap/persistent.h"
#include "third_party/blink/renderer/platform/scheduler/public/agent_group_scheduler.h"
#include "third_party/blink/renderer/platform/scheduler/public/dummy_schedulers.h"
#include "third_party/blink/renderer/platform/scheduler/public/post_cross_thread_task.h"
#include "third_party/blink/renderer/platform/scheduler/public/thread.h"
#include "third_party/blink/renderer/platform/scheduler/public/thread_type.h"
#include "third_party/blink/renderer/platform/storage/blink_storage_key.h"
#include "third_party/blink/renderer/platform/wtf/cross_thread_functional.h"
#include "third_party/blink/renderer/platform/wtf/hash_map.h"
#include "third_party/blink/renderer/platform/wtf/render_thread_state.h"
#include "third_party/blink/renderer/platform/wtf/shared_buffer.h"
#include "third_party/blink/renderer/platform/wtf/thread_safe_ref_counted.h"
#include "v8/include/v8.h"

namespace blink {

// Tasks the render thread needs the main thread to run while it blocks on
// them (creating its GPU context). They are posted to the main thread as
// usual, and are also run by RenderThread::RunQuery() when the main thread is
// itself blocked on the render thread, which would otherwise deadlock.
class RenderThreadMainCalls final
    : public ThreadSafeRefCounted<RenderThreadMainCalls> {
 public:
  explicit RenderThreadMainCalls(
      scoped_refptr<base::SingleThreadTaskRunner> main_task_runner)
      : main_task_runner_(std::move(main_task_runner)) {}

  // Any thread.
  void Post(CrossThreadOnceClosure task) {
    {
      base::AutoLock locker(lock_);
      pending_.push_back(std::move(task));
    }
    wake_.Signal();
    PostCrossThreadTask(
        *main_task_runner_, FROM_HERE,
        CrossThreadBindOnce(&RenderThreadMainCalls::RunPending,
                            scoped_refptr<RenderThreadMainCalls>(this)));
  }

  // Any thread.
  void WakeMainThread() { wake_.Signal(); }

  // Main thread.
  void WaitAndRun() {
    wake_.Wait();
    RunPending();
  }

  // Main thread.
  void RunPending() {
    Vector<CrossThreadOnceClosure> tasks;
    {
      base::AutoLock locker(lock_);
      tasks.swap(pending_);
    }
    for (auto& task : tasks) {
      std::move(task).Run();
    }
  }

 private:
  friend class ThreadSafeRefCounted<RenderThreadMainCalls>;
  ~RenderThreadMainCalls() = default;

  const scoped_refptr<base::SingleThreadTaskRunner> main_task_runner_;
  base::Lock lock_;
  Vector<CrossThreadOnceClosure> pending_ GUARDED_BY(lock_);
  base::WaitableEvent wake_{base::WaitableEvent::ResetPolicy::AUTOMATIC,
                            base::WaitableEvent::InitialState::NOT_SIGNALED};
};

// Friend of Element.
class RenderThreadReplicaAccess {
  STATIC_ONLY(RenderThreadReplicaAccess);

 public:
  static FocusableState FocusableStateOf(const Element& element) {
    return element.IsFocusableState(Element::UpdateBehavior::kStyleAndLayout);
  }
};

namespace {

// While the render thread renders, journal entries that were recorded inside
// a task that is still running are applied once they are this old. This is
// what keeps the page updating while the main thread is stuck in a long
// script task.
constexpr base::TimeDelta kApplyUncommittedAfter = base::Milliseconds(20);
constexpr base::TimeDelta kResourceRetryDelay = base::Milliseconds(100);
// The render thread takes over rendering once the main thread has been inside
// one task for this long while the page is changing (about three frames).
constexpr base::TimeDelta kTakeoverDelay = base::Milliseconds(50);
// How often the render thread checks whether the main thread is stuck, while
// the page is changing.
constexpr base::TimeDelta kWatchdogInterval = base::Milliseconds(16);

using Mode = RenderThreadChannel::Mode;

class ReplicaPage;

// Each render thread owns exactly one replica page.
constinit thread_local ReplicaPage* g_replica = nullptr;

class ReplicaChromeClient final : public EmptyChromeClient {
 public:
  ReplicaChromeClient(ReplicaPage* host, display::ScreenInfos screen_infos)
      : host_(host), screen_infos_(std::move(screen_infos)) {}

  void ClearHost() { host_ = nullptr; }

  void ScheduleAnimation(const LocalFrameView*,
                         cc::BeginMainFrameReason,
                         base::TimeDelta delay,
                         bool) override;

  const display::ScreenInfo& GetScreenInfo(LocalFrame&) const override {
    return screen_infos_.current();
  }
  const display::ScreenInfos& GetScreenInfos(LocalFrame&) const override {
    return screen_infos_;
  }
  const display::ScreenInfo& GetOriginalScreenInfo(LocalFrame&) const override {
    return screen_infos_.current();
  }

 private:
  raw_ptr<ReplicaPage> host_;
  display::ScreenInfos screen_infos_;
};

// The replica never loads anything: FrameFetchContext blocks every non-data
// request for render thread replicas. Should a loader still be created, it
// fails immediately instead of reaching the network.
class ReplicaFrameClient final : public EmptyLocalFrameClient {
 public:
  scoped_refptr<network::SharedURLLoaderFactory> GetURLLoaderFactory()
      override {
    return base::MakeRefCounted<network::SingleRequestURLLoaderFactory>(
        base::BindOnce(
            [](const network::ResourceRequest&,
               mojo::PendingReceiver<network::mojom::URLLoader>,
               mojo::PendingRemote<network::mojom::URLLoaderClient>) {}));
  }
};

using NodeMap = GCedHeapHashMap<uint32_t, Member<Node>>;
using NodeIdMap = GCedHeapHashMap<Member<Node>, uint32_t>;

// A replica of one main frame document, owned by the render thread. It
// applies the main thread's journal, runs the document lifecycle (style,
// layout, paint), rasterizes the result and submits it to viz as a
// compositor frame, all on the render thread.
class ReplicaPage final : public CanvasResourceDispatcherClient,
                          public CanvasResourceProviderDelegate {
 public:
  ReplicaPage(int id,
              v8::Isolate* isolate,
              std::unique_ptr<RenderThreadReplicaParams> params)
      : id_(id), isolate_(isolate), channel_(std::move(params->channel)) {
    TRACE_EVENT0("blink", "ReplicaPage::ReplicaPage");
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);

    agent_group_scheduler_ = scheduler::CreateDummyAgentGroupScheduler(isolate);
    chrome_client_ = MakeGarbageCollected<ReplicaChromeClient>(
        this, std::move(params->screen_infos));
    Page* page = Page::CreateNonOrdinary(
        *chrome_client_, *agent_group_scheduler_,
        params->color_maps ? &*params->color_maps : nullptr);
    Settings& settings = page->GetSettings();
    RenderThread::CopySettings(settings, *params->settings);
    settings.SetScriptEnabled(false);
    settings.SetPluginsEnabled(false);
    // Paint is flattened into a single raster on this thread; there is no
    // cc::LayerTreeHost here.
    settings.SetAcceleratedCompositingEnabled(false);

    frame_client_ = MakeGarbageCollected<ReplicaFrameClient>();
    auto* frame = MakeGarbageCollected<LocalFrame>(
        frame_client_, *page, nullptr, nullptr, nullptr,
        FrameInsertType::kInsertInConstructor, LocalFrameToken(), nullptr,
        nullptr, mojo::NullRemote());
    frame->SetView(MakeGarbageCollected<LocalFrameView>(*frame));
    frame->Init(/*opener=*/nullptr, DocumentToken(),
                /*policy_container=*/nullptr, StorageKey(),
                /*document_ukm_source_id=*/ukm::kInvalidSourceId,
                /*creator_base_url=*/KURL());
    frame->View()->SetCanHaveScrollbars(true);
    page_ = page;
    frame_ = frame;

    static const char kInitialMarkup[] = "<!DOCTYPE html>";
    scoped_refptr<SharedBuffer> data = SharedBuffer::Create(
        base::span<const char>(kInitialMarkup, sizeof(kInitialMarkup) - 1));
    frame->ForceSynchronousDocumentInstall(AtomicString("text/html"), *data,
                                           params->url);
    Document* document = frame->GetDocument();
    document->SetIsRenderThreadReplica();
    document->RemoveChildren();

    page->GetFocusController().SetActive(true);
    page->GetFocusController().SetFocused(true);

    nodes_ = MakeGarbageCollected<NodeMap>();
    node_ids_ = MakeGarbageCollected<NodeIdMap>();
    Remember(1, document);

    // Creating the GPU context from a non-main thread needs one round trip to
    // the main thread. Do it now, before the first frame is needed.
    gpu_compositing_ = SharedGpuContext::IsGpuCompositingEnabled();

    dispatcher_ = std::make_unique<CanvasResourceDispatcher>(
        this, base::SingleThreadTaskRunner::GetCurrentDefault(),
        params->frame_sink_id.client_id(), params->frame_sink_id.sink_id(),
        gfx::Size(1, 1));
    LOG(INFO) << "[OMT] replica " << id_
              << " created on render thread, gpu=" << gpu_compositing_;
    Wake();
  }

  ~ReplicaPage() override {
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);
    frame_request_timer_.Stop();
    watchdog_.Stop();
    chrome_client_->ClearHost();
    // Return exported resources while their provider is still alive.
    dispatcher_.reset();
    provider_.reset();
    clear_provider_.reset();
    // Keep all GC roots until frame/document teardown has completed.
    if (page_) {
      page_->WillBeDestroyed();
    }
  }

  // The main thread pushed journal entries or changed the mode.
  void Wake() {
    channel_->ClearWakePending();
    if (channel_->GetMode() != Mode::kMain) {
      presenting_ = true;
      dispatcher_->SetNeedsBeginFrame(true);
      return;
    }
    Follow();
  }

  void RequestFrame() {
    frame_requested_ = true;
    if (presenting_) {
      dispatcher_->SetNeedsBeginFrame(true);
    }
  }

  // While the main thread renders (Mode::kMain): keep the replica's DOM and
  // style in step with the main thread, without layout, paint or frames, and
  // watch for the main thread getting stuck.
  void Follow() {
    TRACE_EVENT0("blink", "ReplicaPage::Follow");
    if (presenting_) {
      StopPresenting();
    }
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);
    bool has_uncommitted = false;
    Vector<RenderThreadOp> ops = channel_->TakeReadyOps(
        base::TimeTicks::Now(), base::TimeDelta::Max(), &has_uncommitted);
    if (!ops.empty()) {
      ApplyOps(ops);
    }
    if (clear_frame_needed_) {
      SubmitClearFrame();
    }
    // Creating raster resources needs the main thread (see
    // RenderThreadMainCalls), which is only reliably available while it is
    // responsive. Keep the raster provider ready for a takeover.
    if (!size_.IsEmpty() && (!provider_ || !provider_->IsValid())) {
      EnsureProvider();
    }
    if (has_uncommitted || HasRunningAnimations()) {
      if (!watchdog_.IsRunning()) {
        watchdog_.Start(FROM_HERE, kWatchdogInterval, this,
                        &ReplicaPage::CheckMainThread);
      }
    } else {
      watchdog_.Stop();
    }
  }

  void CheckMainThread() {
    if (channel_->GetMode() != Mode::kMain) {
      watchdog_.Stop();
      return;
    }
    const base::TimeTicks now = base::TimeTicks::Now();
    if (channel_->TakeoverAllowed() && !size_.IsEmpty() &&
        channel_->MainTaskDuration(now) >= kTakeoverDelay &&
        (channel_->HasOps() || HasRunningAnimations())) {
      TakeOver();
      return;
    }
    Follow();
  }

  // The main thread is stuck in a long task while the page is changing.
  void TakeOver() {
    if (!channel_->ChangeMode(Mode::kMain, Mode::kRender)) {
      return;
    }
    watchdog_.Stop();
    ++takeovers_;
    TRACE_EVENT_INSTANT(
        "blink", "ReplicaPage::TakeOver", "main_task_ms",
        channel_->MainTaskDuration(base::TimeTicks::Now()).InMillisecondsF());
    if (takeovers_ <= 10 || takeovers_ % 100 == 0) {
      LOG(INFO)
          << "[OMT] replica " << id_
          << " took over rendering from the busy main thread (#" << takeovers_
          << ", main task running for "
          << channel_->MainTaskDuration(base::TimeTicks::Now()).InMilliseconds()
          << " ms)";
    }
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);
    // Everything the main thread did so far, including the running task.
    bool has_uncommitted = false;
    Vector<RenderThreadOp> ops = channel_->TakeReadyOps(
        base::TimeTicks::Now(), base::TimeDelta(), &has_uncommitted);
    if (!ops.empty()) {
      ApplyOps(ops);
    }
    ApplyScrollOffsets();
    presenting_ = true;
    RequestFrame();
  }

  // Rendering is back on the main thread and its frames are on screen.
  void StopPresenting() {
    TRACE_EVENT0("blink", "ReplicaPage::StopPresenting");
    presenting_ = false;
    frame_requested_ = false;
    frame_request_timer_.Stop();
    dispatcher_->SetNeedsBeginFrame(false);
    SubmitClearFrame();
  }

  bool HasRunningAnimations() {
    Document& document = *frame_->GetDocument();
    DocumentTimeline& timeline = document.Timeline();
    const AnimationTimeDelta now(base::TimeTicks::Now().since_origin());
    for (Animation* animation : timeline.GetAnimations()) {
      if (!animation) {
        continue;
      }
      const V8AnimationPlayState::Enum state =
          animation->CalculateAnimationPlayState();
      if (state != V8AnimationPlayState::Enum::kRunning) {
        continue;
      }
      std::optional<AnimationTimeDelta> start = animation->StartTimeInternal();
      AnimationEffect* effect = animation->effect();
      if (!start || !effect) {
        return true;
      }
      if (timeline.ZeroTime() + *start + effect->NormalizedTiming().end_time >
          now) {
        return true;
      }
    }
    return false;
  }

  void ApplyScrollOffsets() {
    for (const auto& entry : scroll_offsets_) {
      Node* target = NodeFor(entry.key);
      auto* element = DynamicTo<Element>(target);
      if (auto* target_document = DynamicTo<Document>(target)) {
        element = target_document->ScrollingElementNoLayout();
      }
      if (!element) {
        continue;
      }
      element->setScrollLeft(entry.value.x());
      element->setScrollTop(entry.value.y());
    }
    scroll_offsets_.clear();
  }

  // Makes the render thread's surface transparent, so that the main thread's
  // own rendering below it shows. A 1x1 transparent resource is stretched
  // over the surface; the surface keeps the viewport size, since resizing it
  // needs the main thread.
  void SubmitClearFrame() {
    clear_frame_needed_ = false;
    if (size_.IsEmpty()) {
      return;
    }
    if (!clear_provider_ || !clear_provider_->IsValid()) {
      clear_provider_ = CreateProvider(gfx::Size(1, 1));
      if (!clear_provider_) {
        return;
      }
    }
    cc::PaintRecorder recorder;
    recorder.beginRecording()->drawColor(SkColors::kTransparent,
                                         SkBlendMode::kSrc);
    clear_provider_->RasterRecord(recorder.finishRecordingAsPicture());
    scoped_refptr<CanvasResource> resource =
        clear_provider_->ProduceCanvasResource();
    if (!resource) {
      clear_provider_.reset();
      return;
    }
    dispatcher_->DispatchFrame(
        base::MakeRefCounted<ExportedCanvasResource>(std::move(resource)),
        gfx::Rect(size_), /*is_opaque=*/false);
  }

  void RequestFrameAfter(base::TimeDelta delay) {
    if (frame_request_timer_.IsRunning() &&
        frame_request_timer_.desired_run_time() <=
            base::TimeTicks::Now() + delay) {
      return;
    }
    frame_request_timer_.Start(FROM_HERE, delay, this,
                               &ReplicaPage::RequestFrame);
  }

  // CanvasResourceDispatcherClient:
  bool BeginFrame() override {
    TRACE_EVENT0("blink", "ReplicaPage::BeginFrame");
    if (channel_->GetMode() == Mode::kMain) {
      dispatcher_->SetNeedsBeginFrame(false);
      Follow();
      return false;
    }
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);
    const base::TimeTicks now = base::TimeTicks::Now();
    bool has_uncommitted = false;
    Vector<RenderThreadOp> ops =
        channel_->TakeReadyOps(now, kApplyUncommittedAfter, &has_uncommitted);
    const bool frame_was_requested = frame_requested_;
    frame_requested_ = false;
    if (!ops.empty()) {
      ApplyOps(ops);
    }
    bool submitted = false;
    if (!size_.IsEmpty() && (frame_was_requested || !ops.empty())) {
      page_->Animator().ServiceScriptedAnimations(now);
      if (frame_->View()->UpdateAllLifecyclePhases(
              DocumentUpdateReason::kBeginMainFrame)) {
        submitted = Paint();
      }
      if (!submitted) {
        // A failed allocation/context recovery must not consume the last
        // request forever, nor spin continuously at the display refresh rate.
        RequestFrameAfter(kResourceRetryDelay);
      }
    }
    dispatcher_->SetNeedsBeginFrame(frame_requested_ || has_uncommitted);
    return submitted;
  }

  // Answers a synchronous query from the main thread. The main thread
  // committed the journal before sending the query, so all of it is applied
  // first; style and layout are then brought up to date by the regular
  // Element/TreeScope APIs of the replica, exactly as they would be on the
  // main thread without off-main-thread rendering.
  void AnswerQuery(RenderThreadQuery& query) {
    TRACE_EVENT1("blink", "ReplicaPage::AnswerQuery", "type",
                 static_cast<int>(query.type));
    v8::Isolate::Scope isolate_scope(isolate_);
    v8::HandleScope handle_scope(isolate_);
    v8::Isolate::DisallowJavascriptExecutionScope no_script(
        isolate_,
        v8::Isolate::DisallowJavascriptExecutionScope::CRASH_ON_FAILURE);
    bool has_uncommitted = false;
    Vector<RenderThreadOp> ops = channel_->TakeReadyOps(
        base::TimeTicks::Now(), kApplyUncommittedAfter, &has_uncommitted);
    if (!ops.empty()) {
      ApplyOps(ops);
      RequestFrame();
    }
    ++queries_;

    using Type = RenderThreadQuery::Type;
    Node* node = NodeFor(query.node);
    auto* element = DynamicTo<Element>(node);
    auto* html = DynamicTo<HTMLElement>(node);
    TreeScope* scope = nullptr;
    if (auto* document = DynamicTo<Document>(node)) {
      scope = document;
    } else if (auto* shadow_root = DynamicTo<ShadowRoot>(node)) {
      scope = shadow_root;
    }
    switch (query.type) {
      case Type::kOffsetLeft:
        query.number = html ? html->offsetLeftForBinding() : 0;
        break;
      case Type::kOffsetTop:
        query.number = html ? html->offsetTopForBinding() : 0;
        break;
      case Type::kOffsetWidth:
        query.number = html ? html->offsetWidthForBinding() : 0;
        break;
      case Type::kOffsetHeight:
        query.number = html ? html->offsetHeightForBinding() : 0;
        break;
      case Type::kClientLeft:
        query.number = element ? element->clientLeft() : 0;
        break;
      case Type::kClientTop:
        query.number = element ? element->clientTop() : 0;
        break;
      case Type::kClientWidth:
        query.number = element ? element->clientWidth() : 0;
        break;
      case Type::kClientHeight:
        query.number = element ? element->clientHeight() : 0;
        break;
      case Type::kScrollLeft:
        query.number = element ? element->scrollLeft() : 0;
        break;
      case Type::kScrollTop:
        query.number = element ? element->scrollTop() : 0;
        break;
      case Type::kScrollWidth:
        query.number = element ? element->scrollWidth() : 0;
        break;
      case Type::kScrollHeight:
        query.number = element ? element->scrollHeight() : 0;
        break;
      case Type::kOffsetParent:
        query.result_node = html ? IdOf(html->unclosedOffsetParent()) : 0;
        break;
      case Type::kBoundingClientRect:
        if (element) {
          DOMRect* rect = element->GetBoundingClientRect();
          query.rects.push_back(
              gfx::RectF(rect->x(), rect->y(), rect->width(), rect->height()));
        }
        break;
      case Type::kClientRects:
        if (element) {
          DOMRectList* list = element->getClientRects();
          for (unsigned i = 0; i < list->length(); ++i) {
            DOMRect* rect = list->item(i);
            query.rects.push_back(gfx::RectF(rect->x(), rect->y(),
                                             rect->width(), rect->height()));
          }
        }
        break;
      case Type::kComputedStyle:
        if (element) {
          CSSStyleDeclaration* declaration =
              MakeGarbageCollected<CSSComputedStyleDeclaration>(
                  element, /*allow_visited_style=*/false, query.pseudo);
          query.text = declaration->getPropertyValue(query.text);
        } else {
          query.text = String();
        }
        break;
      case Type::kInnerText:
        query.text = html ? html->innerText() : String();
        break;
      case Type::kElementFromPoint:
        query.result_node =
            scope ? IdOf(scope->ElementFromPoint(query.x, query.y)) : 0;
        break;
      case Type::kHitTest: {
        Document& document = *frame_->GetDocument();
        document.UpdateStyleAndLayout(DocumentUpdateReason::kHitTest);
        LayoutView* layout_view = document.GetLayoutView();
        if (!layout_view) {
          break;
        }
        HitTestLocation location(
            PhysicalOffset::FromPointFRound(gfx::PointF(query.x, query.y)));
        HitTestResult result(
            HitTestRequest(HitTestRequest::kReadOnly | HitTestRequest::kActive),
            location);
        layout_view->HitTest(location, result);
        // Nodes that exist only on this thread (user agent shadow trees,
        // anonymous content) map to their nearest replicated ancestor.
        Node* hit = result.InnerNode();
        while (hit && !IdOf(hit)) {
          hit = hit->ParentOrShadowHostNode();
        }
        query.result_node = IdOf(hit);
        query.result_x = result.LocalPoint().left.ToDouble();
        query.result_y = result.LocalPoint().top.ToDouble();
        break;
      }
      case Type::kMouseRelativePosition:
        if (node && query.rects.size() == 2) {
          node->GetDocument().UpdateStyleAndLayout(
              DocumentUpdateReason::kInput);
          gfx::PointF offset = query.rects[0].origin();
          gfx::PointF layer_location = query.rects[1].origin();
          MouseEvent::ComputeRelativePositionFromLayout(
              *node, gfx::PointF(query.x, query.y),
              static_cast<float>(query.number), offset, layer_location);
          query.rects = {gfx::RectF(offset, gfx::SizeF()),
                         gfx::RectF(layer_location, gfx::SizeF())};
        }
        break;
      case Type::kRangeClientRects:
      case Type::kRangeBoundingClientRect: {
        Node* end = NodeFor(query.node2);
        if (!node || !end) {
          break;
        }
        auto* range = Range::Create(*frame_->GetDocument());
        range->setStart(node, static_cast<unsigned>(query.x), IGNORE_EXCEPTION);
        range->setEnd(end, static_cast<unsigned>(query.y), IGNORE_EXCEPTION);
        if (query.type == Type::kRangeBoundingClientRect) {
          DOMRect* rect = range->getBoundingClientRect();
          query.rects.push_back(
              gfx::RectF(rect->x(), rect->y(), rect->width(), rect->height()));
        } else {
          DOMRectList* list = range->getClientRects();
          for (unsigned i = 0; i < list->length(); ++i) {
            DOMRect* rect = list->item(i);
            query.rects.push_back(gfx::RectF(rect->x(), rect->y(),
                                             rect->width(), rect->height()));
          }
        }
        break;
      }
      case Type::kInnerWidth:
      case Type::kInnerHeight:
      case Type::kWindowScrollX:
      case Type::kWindowScrollY: {
        LocalDOMWindow* window = frame_->DomWindow();
        if (!window) {
          break;
        }
        query.number = query.type == Type::kInnerWidth ? window->innerWidth()
                       : query.type == Type::kInnerHeight
                           ? window->innerHeight()
                       : query.type == Type::kWindowScrollX ? window->scrollX()
                                                            : window->scrollY();
        break;
      }
      case Type::kFocusableState:
        query.number =
            element ? static_cast<int>(
                          RenderThreadReplicaAccess::FocusableStateOf(*element))
                    : static_cast<int>(FocusableState::kNotFocusable);
        break;
      case Type::kAnimationTimings: {
        Document& document = *frame_->GetDocument();
        for (Animation* animation :
             document.GetDocumentAnimations().getAnimations(document)) {
          auto* transition = DynamicTo<CSSTransition>(animation);
          auto* css_animation = DynamicTo<CSSAnimation>(animation);
          auto* timeline =
              DynamicTo<DocumentTimeline>(animation->TimelineInternal());
          std::optional<AnimationTimeDelta> start =
              animation->StartTimeInternal();
          if ((!transition && !css_animation) || !timeline || !start ||
              animation->CalculateAnimationPlayState() !=
                  V8AnimationPlayState::Enum::kRunning) {
            continue;
          }
          Element* owner = transition ? transition->OwningElement()
                                      : css_animation->OwningElement();
          const uint32_t id = IdOf(owner);
          if (!id) {
            continue;
          }
          query.timings.push_back(RenderThreadAnimationTiming{
              .node = id,
              .is_transition = !!transition,
              .name = transition ? transition->TransitionCSSPropertyName()
                                       .ToAtomicString()
                                       .GetString()
                                 : css_animation->animationName(),
              .start_ms = (timeline->ZeroTime() + *start).InMillisecondsF()});
        }
        break;
      }
      case Type::kElementsFromPoint:
        if (scope) {
          for (Element* hit : scope->ElementsFromPoint(query.x, query.y)) {
            if (uint32_t id = IdOf(hit)) {
              query.result_nodes.push_back(id);
            }
          }
        }
        break;
    }
    query.answered = true;
    if (queries_ == 1) {
      LOG(INFO) << "[OMT] replica " << id_
                << " answered its first layout query on the render thread";
    }
  }

  // CanvasResourceProviderDelegate:
  void NotifyGpuContextLost() override {
    provider_.reset();
    clear_provider_.reset();
    RequestFrame();
  }
  void InitializeForRecording(cc::PaintCanvas*) const override {}

 private:
  void Remember(uint32_t id, Node* node) {
    nodes_->Set(id, node);
    node_ids_->Set(node, id);
  }

  void ForgetSubtree(Node& node) {
    auto it = node_ids_->find(&node);
    if (it != node_ids_->end()) {
      nodes_->erase(it->value);
      node_ids_->erase(it);
    }
    if (auto* element = DynamicTo<Element>(node)) {
      if (ShadowRoot* root = element->GetShadowRoot();
          root && !root->IsUserAgent()) {
        ForgetSubtree(*root);
      }
    }
    if (auto* container = DynamicTo<ContainerNode>(node)) {
      for (Node* child = container->firstChild(); child;
           child = child->nextSibling()) {
        ForgetSubtree(*child);
      }
    }
  }

  uint32_t IdOf(const Node* node) const {
    if (!node) {
      return 0;
    }
    auto it = node_ids_->find(const_cast<Node*>(node));
    return it == node_ids_->end() ? 0u : it->value;
  }

  Node* NodeFor(uint32_t id) {
    if (!id) {
      return nullptr;
    }
    auto it = nodes_->find(id);
    return it == nodes_->end() ? nullptr : it->value.Get();
  }

  static QualifiedName NameFor(const RenderThreadOp& op) {
    return QualifiedName(AtomicString(op.prefix), AtomicString(op.local_name),
                         AtomicString(op.ns));
  }

  void ApplyOps(Vector<RenderThreadOp>& ops) {
    TRACE_EVENT1("blink", "ReplicaPage::ApplyOps", "count", ops.size());
    for (RenderThreadOp& op : ops) {
      Apply(op);
    }
    ops_applied_ += ops.size();
  }

  void Apply(RenderThreadOp& op) {
    using Type = RenderThreadOp::Type;
    Document& document = *frame_->GetDocument();
    switch (op.type) {
      case Type::kCreateElement: {
        Element* element = document.CreateRawElement(NameFor(op));
        Remember(op.node, element);
        return;
      }
      case Type::kCreateText:
        Remember(op.node, Text::Create(document, op.text));
        return;
      case Type::kCreateComment:
        Remember(op.node, Comment::Create(document, op.text));
        return;
      case Type::kCreateDoctype:
        Remember(op.node, MakeGarbageCollected<DocumentType>(
                              &document, op.local_name, op.ns, op.prefix));
        return;
      case Type::kAttachShadowRoot: {
        auto* host = DynamicTo<Element>(NodeFor(op.parent));
        if (!host || host->GetShadowRoot()) {
          return;
        }
        ShadowRoot& root = host->AttachShadowRootInternal(
            static_cast<ShadowRootMode>(op.int_value),
            (op.int_value2 & 1) ? FocusDelegation::kDelegateFocus
                                : FocusDelegation::kNone,
            (op.int_value2 & 2) ? SlotAssignmentMode::kManual
                                : SlotAssignmentMode::kNamed,
            CustomElementRegistryAssignment::Inherit(),
            /*serializable=*/false, /*clonable=*/false,
            /*reference_target=*/g_null_atom);
        Remember(op.node, &root);
        return;
      }
      case Type::kSetAttribute:
        if (auto* element = DynamicTo<Element>(NodeFor(op.node))) {
          element->setAttribute(NameFor(op), AtomicString(op.text));
        }
        return;
      case Type::kRemoveAttribute:
        if (auto* element = DynamicTo<Element>(NodeFor(op.node))) {
          element->removeAttribute(NameFor(op));
        }
        return;
      case Type::kInsert: {
        auto* parent = DynamicTo<ContainerNode>(NodeFor(op.parent));
        Node* child = NodeFor(op.node);
        if (!parent || !child) {
          return;
        }
        Node* before = NodeFor(op.before);
        if (before && before->parentNode() != parent) {
          before = nullptr;
        }
        parent->InsertBefore(child, before, IGNORE_EXCEPTION);
        return;
      }
      case Type::kRemove:
        if (Node* node = NodeFor(op.node)) {
          if (ContainerNode* parent = node->parentNode()) {
            parent->RemoveChild(node, IGNORE_EXCEPTION);
          }
          ForgetSubtree(*node);
        }
        return;
      case Type::kRemoveAllChildren:
        if (auto* parent = DynamicTo<ContainerNode>(NodeFor(op.parent))) {
          for (Node* child = parent->firstChild(); child;
               child = child->nextSibling()) {
            ForgetSubtree(*child);
          }
          parent->RemoveChildren();
        }
        return;
      case Type::kSetText:
        if (auto* data = DynamicTo<CharacterData>(NodeFor(op.node))) {
          data->setData(op.text);
        }
        return;
      case Type::kSetSheetText:
        if (Node* node = NodeFor(op.node)) {
          node->setTextContent(op.text);
        }
        return;
      case Type::kSetElementState: {
        auto* element = DynamicTo<Element>(NodeFor(op.node));
        if (!element) {
          return;
        }
        const bool value = op.int_value2;
        switch (static_cast<RenderThreadOp::ElementState>(op.int_value)) {
          case RenderThreadOp::ElementState::kHovered:
            element->SetHovered(value);
            break;
          case RenderThreadOp::ElementState::kActive:
            element->SetActive(value);
            break;
          case RenderThreadOp::ElementState::kFocused:
            element->SetFocused(value, mojom::blink::FocusType::kNone);
            break;
          case RenderThreadOp::ElementState::kChecked:
            if (auto* input = DynamicTo<HTMLInputElement>(element)) {
              input->SetChecked(value,
                                TextFieldEventBehavior::kDispatchNoEvent);
            }
            break;
        }
        return;
      }
      case Type::kSetViewport: {
        const gfx::Size size(op.int_value, op.int_value2);
        const float zoom = op.float_value > 0 ? op.float_value : 1.f;
        if (zoom != frame_->LayoutZoomFactor()) {
          frame_->SetLayoutZoomFactor(zoom);
        }
        if (size != size_) {
          size_ = size;
          frame_->View()->Resize(size);
          page_->GetVisualViewport().SetSize(size);
          if (!size.IsEmpty()) {
            dispatcher_->Reshape(size);
            // The main thread embeds the resized surface once it has a frame.
            clear_frame_needed_ = !presenting_;
          }
          provider_.reset();
        }
        RequestFrame();
        return;
      }
      case Type::kSetScrollOffset:
        scroll_offsets_.Set(op.node,
                            gfx::PointF(op.float_value, op.float_value2));
        if (presenting_) {
          ApplyScrollOffsets();
        }
        return;
      case Type::kStyleSync: {
        // The main thread updated style at this point, with this animation
        // time. Do the same, so that CSS transitions and animations start
        // exactly as on the main thread.
        AnimationClock& clock = page_->Animator().Clock();
        clock.SetAllowedToDynamicallyUpdateTime(false);
        clock.UpdateTime(base::TimeTicks() + base::Microseconds(op.time));
        document.UpdateStyleAndLayoutTree();
        if (op.int_value == 1) {
          document.GetPendingAnimations().Update(nullptr,
                                                 /*start_on_compositor=*/false);
        }
        return;
      }
      case Type::kScrollElement: {
        Node* target = NodeFor(op.node);
        auto* element = DynamicTo<Element>(target);
        if (auto* target_document = DynamicTo<Document>(target)) {
          element = target_document->ScrollingElementNoLayout();
        }
        if (!element) {
          return;
        }
        const bool relative = op.int_value & 4;
        if (op.int_value & 1) {
          element->setScrollLeft(op.float_value +
                                 (relative ? element->scrollLeft() : 0));
        }
        if (op.int_value & 2) {
          element->setScrollTop(op.float_value2 +
                                (relative ? element->scrollTop() : 0));
        }
        return;
      }
      case Type::kSetCompatMode:
        document.SetCompatibilityMode(
            static_cast<Document::CompatibilityMode>(op.int_value));
        return;
    }
  }

  std::unique_ptr<Canvas2DResourceProvider> CreateProvider(
      const gfx::Size& size) {
    std::unique_ptr<Canvas2DResourceProvider> provider;
    const Canvas2DColorParams color_params;
    // Re-query after context loss: viz may have fallen back to software.
    gpu_compositing_ = SharedGpuContext::IsGpuCompositingEnabled();
    if (gpu_compositing_) {
      auto context_provider = SharedGpuContext::ContextProviderWrapper();
      provider = Canvas2DResourceProvider::CreateWithClear(
          size, color_params.GetSharedImageFormat(),
          color_params.GetAlphaType(), color_params.GetGfxColorSpace(),
          context_provider, RasterMode::kGPU,
          gpu::SHARED_IMAGE_USAGE_DISPLAY_READ, this);
      if (!provider) {
        // CPU raster with GPU compositing still requires a GPU-backed shared
        // image; the software-compositor factory explicitly rejects this mode.
        provider = Canvas2DResourceProvider::CreateWithClear(
            size, color_params.GetSharedImageFormat(),
            color_params.GetAlphaType(), color_params.GetGfxColorSpace(),
            context_provider, RasterMode::kCPU,
            gpu::SHARED_IMAGE_USAGE_DISPLAY_READ, this);
      }
    } else {
      provider = Canvas2DResourceProvider::CreateWithClearForSoftwareCompositor(
          size, color_params.GetSharedImageFormat(),
          color_params.GetAlphaType(), color_params.GetGfxColorSpace(),
          SharedGpuContext::SharedImageInterfaceProvider(), this);
    }
    return provider;
  }

  bool EnsureProvider() {
    if (provider_ && provider_->IsValid()) {
      return true;
    }
    provider_ = CreateProvider(size_);
    if (!provider_) {
      LOG(ERROR) << "[OMT] could not create a resource provider";
      return false;
    }
    LOG(INFO) << "[OMT] replica " << id_ << " raster provider "
              << size_.ToString()
              << (provider_->IsAccelerated() ? " (gpu)" : " (software)");
    return true;
  }

  bool Paint() {
    TRACE_EVENT0("blink", "ReplicaPage::Paint");
    if (!EnsureProvider()) {
      return false;
    }
    cc::PaintRecorder recorder;
    cc::PaintCanvas* canvas = recorder.beginRecording();
    canvas->drawColor(SkColors::kWhite, SkBlendMode::kSrc);
    canvas->drawPicture(frame_->View()->GetPaintRecord());
    provider_->RasterRecord(recorder.finishRecordingAsPicture());
    scoped_refptr<CanvasResource> resource = provider_->ProduceCanvasResource();
    if (!resource) {
      provider_.reset();
      return false;
    }
    dispatcher_->DispatchFrame(
        base::MakeRefCounted<ExportedCanvasResource>(std::move(resource)),
        gfx::Rect(size_), /*is_opaque=*/true);
    if (++frames_ == 1) {
      LOG(INFO) << "[OMT] replica " << id_
                << " submitted its first frame from the render thread ("
                << ops_applied_ << " journal entries applied)";
    }
    return true;
  }

  const int id_;
  const raw_ptr<v8::Isolate> isolate_;
  scoped_refptr<RenderThreadChannel> channel_;
  // Constructed, accessed and cleared only on the backing thread. These roots
  // must never be transferred back to the main-thread heap.
  Persistent<AgentGroupScheduler> agent_group_scheduler_;
  Persistent<ReplicaChromeClient> chrome_client_;
  Persistent<ReplicaFrameClient> frame_client_;
  Persistent<Page> page_;
  Persistent<LocalFrame> frame_;
  Persistent<NodeMap> nodes_;
  Persistent<NodeIdMap> node_ids_;
  std::unique_ptr<CanvasResourceDispatcher> dispatcher_;
  std::unique_ptr<Canvas2DResourceProvider> provider_;
  // 1x1 transparent resource shown while the main thread renders.
  std::unique_ptr<Canvas2DResourceProvider> clear_provider_;
  gfx::Size size_;
  bool gpu_compositing_ = false;
  bool frame_requested_ = false;
  // Producing frames (Mode::kRender or kHandBack).
  bool presenting_ = false;
  bool clear_frame_needed_ = false;
  // Main-thread scroll offsets, applied when taking over, by node id.
  HashMap<uint32_t, gfx::PointF> scroll_offsets_;
  base::RepeatingTimer watchdog_;
  uint64_t takeovers_ = 0;
  uint64_t frames_ = 0;
  uint64_t queries_ = 0;
  size_t ops_applied_ = 0;
  base::OneShotTimer frame_request_timer_;
};

void ReplicaChromeClient::ScheduleAnimation(const LocalFrameView*,
                                            cc::BeginMainFrameReason,
                                            base::TimeDelta delay,
                                            bool) {
  if (!host_) {
    return;
  }
  if (delay.is_positive()) {
    host_->RequestFrameAfter(delay);
  } else {
    host_->RequestFrame();
  }
}

void InitializeRenderThread(WorkerBackingThread* thread,
                            scoped_refptr<RenderThreadMainCalls> main_calls) {
  MarkCurrentThreadAsBlinkRenderThread();
  thread->InitializeOnBackingThread(
      WorkerBackingThreadStartupData::CreateDefault());
  v8::Isolate* isolate = thread->GetIsolate();
  v8::Isolate::Scope isolate_scope(isolate);
  v8::HandleScope handle_scope(isolate);
  V8PerIsolateData::From(isolate)->EnsureMainWorldForRenderThread();
  // GPU context creation hops to the main thread. The main thread may be
  // blocked in RunQuery() waiting for this thread, so let it run such hops.
  SharedGpuContext::SetMainThreadTaskPosterForCurrentThread(
      base::BindRepeating(&RenderThreadMainCalls::Post, main_calls));
}

void CreateReplicaOnRenderThread(
    int id,
    WorkerBackingThread* thread,
    std::unique_ptr<RenderThreadReplicaParams> params) {
  DCHECK(thread->BackingThread().IsCurrentThread());
  CHECK(thread->GetIsolate());
  CHECK(!g_replica);
  g_replica = new ReplicaPage(id, thread->GetIsolate(), std::move(params));
}

void ShutdownRenderThread(
    WorkerBackingThread* thread,
    scoped_refptr<base::SingleThreadTaskRunner> main_task_runner) {
  delete g_replica;
  g_replica = nullptr;
  SharedGpuContext::Reset();
  thread->ShutdownOnBackingThread();
  // Joining the thread has to happen elsewhere; this thread is now idle.
  main_task_runner->PostTask(FROM_HERE,
                             base::BindOnce(
                                 [](WorkerBackingThread* thread) {
                                   delete thread;
                                   LOG(INFO) << "[OMT] render thread stopped";
                                 },
                                 base::Unretained(thread)));
}

void WakeOnRenderThread() {
  if (g_replica) {
    g_replica->Wake();
  }
}

void AnswerQueryOnRenderThread(
    RenderThreadQuery* query,
    std::atomic<bool>* done,
    scoped_refptr<RenderThreadMainCalls> main_calls) {
  if (g_replica) {
    g_replica->AnswerQuery(*query);
  }
  done->store(true, std::memory_order_release);
  main_calls->WakeMainThread();
}

int NextReplicaId() {
  static std::atomic<int> next_id{1};
  return next_id.fetch_add(1, std::memory_order_relaxed);
}

}  // namespace

RenderThreadReplicaParams::RenderThreadReplicaParams() = default;
RenderThreadReplicaParams::~RenderThreadReplicaParams() = default;

RenderThread::RenderThread(std::unique_ptr<RenderThreadReplicaParams> params)
    : thread_(std::make_unique<WorkerBackingThread>(
          ThreadCreationParams(ThreadType::kUnspecifiedWorkerThread)
              .SetThreadNameForTest("BlinkRenderThread"))),
      main_task_runner_(base::SingleThreadTaskRunner::GetCurrentDefault()),
      main_calls_(
          base::MakeRefCounted<RenderThreadMainCalls>(main_task_runner_)) {
  DCHECK(IsMainThread());
  CHECK(params);
  CHECK(params->channel);
  CHECK(params->settings);
  CHECK(params->frame_sink_id.is_valid());
  const int id = NextReplicaId();
  scoped_refptr<base::SingleThreadTaskRunner> runner =
      thread_->BackingThread().GetTaskRunner();
  PostCrossThreadTask(
      *runner, FROM_HERE,
      CrossThreadBindOnce(&InitializeRenderThread,
                          CrossThreadUnretained(thread_.get()), main_calls_));
  PostCrossThreadTask(*runner, FROM_HERE,
                      CrossThreadBindOnce(&CreateReplicaOnRenderThread, id,
                                          CrossThreadUnretained(thread_.get()),
                                          std::move(params)));
  LOG(INFO) << "[OMT] render thread started for replica " << id;
}

RenderThread::~RenderThread() {
  DCHECK(IsMainThread());
  scoped_refptr<base::SingleThreadTaskRunner> runner =
      thread_->BackingThread().GetTaskRunner();
  PostCrossThreadTask(
      *runner, FROM_HERE,
      CrossThreadBindOnce(&ShutdownRenderThread,
                          CrossThreadUnretained(thread_.release()),
                          main_task_runner_));
}

void RenderThread::Wake() {
  DCHECK(IsMainThread());
  PostCrossThreadTask(*thread_->BackingThread().GetTaskRunner(), FROM_HERE,
                      CrossThreadBindOnce(&WakeOnRenderThread));
}

void RenderThread::RunQuery(RenderThreadQuery& query) {
  DCHECK(IsMainThread());
  TRACE_EVENT1("blink", "RenderThread::RunQuery", "type",
               static_cast<int>(query.type));
  std::atomic<bool> done{false};
  PostCrossThreadTask(
      *thread_->BackingThread().GetTaskRunner(), FROM_HERE,
      CrossThreadBindOnce(&AnswerQueryOnRenderThread,
                          CrossThreadUnretained(&query),
                          CrossThreadUnretained(&done), main_calls_));
  while (!done.load(std::memory_order_acquire)) {
    main_calls_->WaitAndRun();
  }
  if (++queries_ == 1) {
    LOG(INFO) << "[OMT] main thread got its first layout answer from the "
                 "render thread";
  }
}

// static
void RenderThread::CopySettings(Settings& to, const Settings& from) {
  to.GetGenericFontFamilySettings() = from.GetGenericFontFamilySettings();
  to.SetMinimumFontSize(from.GetMinimumFontSize());
  to.SetMinimumLogicalFontSize(from.GetMinimumLogicalFontSize());
  to.SetDefaultFontSize(from.GetDefaultFontSize());
  to.SetDefaultFixedFontSize(from.GetDefaultFixedFontSize());
  to.SetImageAnimationPolicy(from.GetImageAnimationPolicy());
  to.SetPrefersReducedMotion(from.GetPrefersReducedMotion());
  to.SetPreferredColorScheme(from.GetPreferredColorScheme());
  to.SetInForcedColors(from.GetInForcedColors());
  to.SetAcceptLanguages(from.GetAcceptLanguages());
  to.SetTextAreasAreResizable(from.GetTextAreasAreResizable());
  to.SetScrollAnimatorEnabled(from.GetScrollAnimatorEnabled());
}

}  // namespace blink
