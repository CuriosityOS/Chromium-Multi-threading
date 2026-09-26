// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_H_

#include <memory>
#include <optional>

#include "base/memory/scoped_refptr.h"
#include "base/task/single_thread_task_runner.h"
#include "components/viz/common/surfaces/frame_sink_id.h"
#include "third_party/blink/public/common/page/color_provider_color_maps.h"
#include "third_party/blink/renderer/core/core_export.h"
#include "third_party/blink/renderer/core/render_thread/render_thread_channel.h"
#include "third_party/blink/renderer/platform/weborigin/kurl.h"
#include "ui/display/screen_infos.h"

namespace blink {

class Settings;
class WorkerBackingThread;

// Everything the render thread needs to build a replica of a main frame
// document. Created on the main thread and moved into the render-thread task;
// no main-thread GC objects may be retained here.
struct CORE_EXPORT RenderThreadReplicaParams {
  RenderThreadReplicaParams();
  ~RenderThreadReplicaParams();

  scoped_refptr<RenderThreadChannel> channel;
  std::unique_ptr<Settings> settings;
  display::ScreenInfos screen_infos;
  std::optional<ColorProviderColorMaps> color_maps;
  KURL url;
  viz::FrameSinkId frame_sink_id;
};

class RenderThreadMainCalls;

// The render thread of one page: a dedicated thread with its own V8 isolate
// and Oilpan heap that owns the replica of the page's main frame document and
// runs style, layout, paint and raster for it.
//
// Each page that uses off-main-thread rendering (see RenderThreadJournal) owns
// one RenderThread. Destroying it tears the replica and the thread down.
//
// All methods are called on the main thread.
class CORE_EXPORT RenderThread {
 public:
  explicit RenderThread(std::unique_ptr<RenderThreadReplicaParams> params);
  RenderThread(const RenderThread&) = delete;
  RenderThread& operator=(const RenderThread&) = delete;
  ~RenderThread();

  // Tells the render thread that new journal entries are available.
  void Wake();

  // Synchronously answers `query` on the render thread: the render thread
  // applies every journal entry pushed so far (the caller commits them first),
  // updates style and layout of the replica and fills in the result. The main
  // thread blocks until then. Requests the render thread makes to the main
  // thread in the meantime (GPU context creation) are run by this wait.
  void RunQuery(RenderThreadQuery& query);

  // Copies the settings that affect rendering (fonts, color scheme, ...).
  static void CopySettings(Settings& to, const Settings& from);

 private:
  std::unique_ptr<WorkerBackingThread> thread_;
  scoped_refptr<base::SingleThreadTaskRunner> main_task_runner_;
  scoped_refptr<RenderThreadMainCalls> main_calls_;
  uint64_t queries_ = 0;
};

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_CORE_RENDER_THREAD_RENDER_THREAD_H_
