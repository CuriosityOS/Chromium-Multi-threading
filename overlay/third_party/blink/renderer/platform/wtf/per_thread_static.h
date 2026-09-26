// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_PER_THREAD_STATIC_H_
#define THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_PER_THREAD_STATIC_H_

#include <type_traits>

#include "third_party/blink/renderer/platform/wtf/leak_annotations.h"

// Like DEFINE_STATIC_LOCAL(), but every thread gets its own instance.
//
// This is used for statics that hold garbage-collected objects through a
// Persistent. A Persistent belongs to the heap of the thread that created it,
// so a single process-wide instance cannot be shared between the main thread
// and the off-main-thread render thread (core/render_thread/). Each thread
// lazily creates its own copy the first time it runs the enclosing function.
// Instances are intentionally leaked, like DEFINE_STATIC_LOCAL().
#define DEFINE_PER_THREAD_STATIC_LOCAL(Type, Name, Arguments)           \
  static constinit thread_local std::remove_cvref_t<Type>* Name##_ptr = \
      nullptr;                                                          \
  if (!Name##_ptr) [[unlikely]] {                                       \
    Name##_ptr = new std::remove_cvref_t<Type> Arguments;               \
    LEAK_SANITIZER_IGNORE_OBJECT(Name##_ptr);                           \
  }                                                                     \
  Type& Name = *Name##_ptr

#endif  // THIRD_PARTY_BLINK_RENDERER_PLATFORM_WTF_PER_THREAD_STATIC_H_
