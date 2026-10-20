---
id: f-os-io-uring-sqpoll-idle-wakeup
type: fact
domain: os
title: An idle SQPOLL thread must be woken explicitly
summary: When the SQPOLL kernel thread has been idle for sq_thread_idle ms it 
  goes to sleep and flags IORING_SQ_NEED_WAKEUP; the application must then call 
  io_uring_enter(2) with IORING_ENTER_SQ_WAKEUP.
claim: After sq_thread_idle milliseconds idle the SQPOLL thread sleeps and sets 
  IORING_SQ_NEED_WAKEUP in the SQ flags.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- пробуждение потока SQPOLL
- IORING_SQ_NEED_WAKEUP
- sq_thread_idle
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
  applies_with:
  - id: f-os-io-uring-enter-submit-and-wait
    w: 0.8
    note: wake the sleeping SQPOLL thread with IORING_ENTER_SQ_WAKEUP
  refines:
  - f-os-io-uring-sqpoll-kernel-thread
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

After sq_thread_idle milliseconds idle the SQPOLL thread sleeps and sets IORING_SQ_NEED_WAKEUP in the SQ flags. [@src-man-io-uring-setup-2 гл. 2 "If the kernel thread is idle for more than sq_thread_idle milliseconds, it will set the IORING_SQ_NEED_WAKEUP bit"]

## Why

Spinning forever would pin a core even when the application is idle.

## Caveats

liburing's io_uring_submit(3) checks the flag and issues the wakeup for you.
