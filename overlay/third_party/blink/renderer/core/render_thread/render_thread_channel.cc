// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/core/render_thread/render_thread_channel.h"

namespace blink {

bool RenderThreadChannel::Push(RenderThreadOp op) {
  base::AutoLock locker(lock_);
  const bool was_empty = ops_.empty();
  if (ops_.size() == committed_) {
    oldest_uncommitted_ = base::TimeTicks::Now();
  }
  ops_.push_back(std::move(op));
  return was_empty;
}

bool RenderThreadChannel::Commit() {
  base::AutoLock locker(lock_);
  if (committed_ == ops_.size()) {
    return false;
  }
  committed_ = ops_.size();
  return true;
}

bool RenderThreadChannel::MarkWakePending() {
  return !wake_pending_.exchange(true, std::memory_order_acq_rel);
}

bool RenderThreadChannel::HasOps() {
  base::AutoLock locker(lock_);
  return !ops_.empty();
}

void RenderThreadChannel::ClearWakePending() {
  wake_pending_.store(false, std::memory_order_release);
}

Vector<RenderThreadOp> RenderThreadChannel::TakeReadyOps(
    base::TimeTicks now,
    base::TimeDelta stale_after,
    bool* has_uncommitted) {
  base::AutoLock locker(lock_);
  wtf_size_t take = committed_;
  if (take < ops_.size() && now - oldest_uncommitted_ >= stale_after) {
    // The main thread has been inside one task for a while (a long script
    // task). Show what it has done so far.
    take = ops_.size();
  }
  Vector<RenderThreadOp> result;
  if (take == ops_.size()) {
    result.swap(ops_);
    committed_ = 0;
  } else if (take) {
    result.reserve(take);
    for (wtf_size_t i = 0; i < take; ++i) {
      result.push_back(std::move(ops_[i]));
    }
    ops_.EraseAt(0, take);
    committed_ = 0;
  }
  *has_uncommitted = !ops_.empty();
  return result;
}

}  // namespace blink
