// Copyright 2016 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "third_party/blink/renderer/core/html/custom/ce_reactions_scope.h"

#include "third_party/blink/renderer/bindings/core/v8/script_promise_resolver.h"
#include "third_party/blink/renderer/core/dom/document.h"
#include "third_party/blink/renderer/core/dom/element.h"
#include "third_party/blink/renderer/core/execution_context/execution_context.h"
#include "third_party/blink/renderer/core/html/custom/custom_element_reaction_stack.h"

namespace blink {

constinit thread_local CEReactionsScope* CEReactionsScope::top_of_stack_ =
    nullptr;

// static
CEReactionsScope* CEReactionsScope::Current() {
  return top_of_stack_;
}

CEReactionsScope::CEReactionsScope(v8::Isolate* isolate)
    : prev_(top_of_stack_), try_catch_(isolate) {
  // Each thread maintains its own reaction-scope stack and isolate.
  top_of_stack_ = this;
}

CEReactionsScope::~CEReactionsScope() {
  if (stack_) {
    stack_->PopInvokingReactions();
  }
  if (try_catch_.HasCaught()) [[unlikely]] {
    try_catch_.ReThrow();
  }
  top_of_stack_ = top_of_stack_->prev_;
}

void CEReactionsScope::EnqueueToCurrentQueue(CustomElementReactionStack& stack,
                                             Element& element,
                                             CustomElementReaction& reaction) {
  if (!stack_)
    stack.Push();
  stack_ = &stack;
  stack.EnqueueToCurrentQueue(element, reaction);
}

}  // namespace blink
