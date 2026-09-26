// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_RENDER_THREAD_STATE_H_
#define THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_RENDER_THREAD_STATE_H_

#include "third_party/blink/renderer/platform/wtf/threading.h"
#include "third_party/blink/renderer/platform/wtf/wtf_export.h"

namespace blink {

// True on the Blink render thread (core/render_thread/), which owns a
// non-scripted replica of the main frame's page and runs style, layout and
// paint for it. Code that is otherwise restricted to the main thread because
// it touches frames/documents may also run there.
WTF_EXPORT bool IsBlinkRenderThread();
WTF_EXPORT void MarkCurrentThreadAsBlinkRenderThread();

inline bool IsMainOrBlinkRenderThread() {
  return IsMainThread() || IsBlinkRenderThread();
}

}  // namespace blink

#endif  // THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_RENDER_THREAD_STATE_H_
