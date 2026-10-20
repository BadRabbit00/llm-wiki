---
id: f-os-io-uring-enter-sq-wakeup
type: fact
domain: os
title: IORING_ENTER_SQ_WAKEUP wakes the SQPOLL thread
summary: On an IORING_SETUP_SQPOLL ring, io_uring_enter(2) with 
  IORING_ENTER_SQ_WAKEUP wakes the kernel submission thread after it went idle; 
  it is the only reason to call enter for submission there.
claim: IORING_ENTER_SQ_WAKEUP asks the kernel to wake the sleeping SQPOLL thread
  so it submits the pending SQEs.
kind: api
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_ENTER_SQ_WAKEUP
- разбудить поток SQPOLL
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-setup-flags
  applies_with:
  - id: f-os-io-uring-sqpoll-idle-wakeup
    w: 0.9
    note: needed once IORING_SQ_NEED_WAKEUP is set
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_ENTER_SQ_WAKEUP asks the kernel to wake the sleeping SQPOLL thread so it submits the pending SQEs. [@src-man-io-uring-enter-2 гл. 2 "this flag asks the kernel to wakeup the SQ kernel thread to submit IO"]

## Why

Without the wakeup the SQEs sit in the ring until the thread is woken by something else.
