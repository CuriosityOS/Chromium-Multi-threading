// Copyright 2020 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/platform/graphics/paint/ignore_paint_timing_scope.h"

namespace blink {

constinit thread_local int IgnorePaintTimingScope::ignore_depth_ = 0;
constinit thread_local bool
    IgnorePaintTimingScope::is_document_element_invisible_ = false;

}  // namespace blink
