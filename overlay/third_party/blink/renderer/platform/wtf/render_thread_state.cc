// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/platform/wtf/render_thread_state.h"

namespace blink {

namespace {
constinit thread_local bool g_is_blink_render_thread = false;
}  // namespace

bool IsBlinkRenderThread() {
  return g_is_blink_render_thread;
}

void MarkCurrentThreadAsBlinkRenderThread() {
  g_is_blink_render_thread = true;
}

}  // namespace blink
