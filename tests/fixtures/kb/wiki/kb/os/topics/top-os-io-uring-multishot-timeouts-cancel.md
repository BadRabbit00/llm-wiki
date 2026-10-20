---
id: top-os-io-uring-multishot-timeouts-cancel
type: topic
domain: os
title: Multishot requests, timeouts and cancellation
summary: Requests that complete many times (accept, recv, poll), 
  IORING_OP_TIMEOUT and its clocks, enter-level wait timeouts, ASYNC_CANCEL 
  results and flags.
priority: 4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- multishot
- таймауты и отмена
- IORING_OP_ASYNC_CANCEL
relations:
  builds_on:
  - top-os-io-uring-submission
  applies_with:
  - top-os-io-uring-provided-buffers
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

Multishot accept (5.19) and recv (6.0) post a CQE per event from one submission; each CQE carries IORING_CQE_F_MORE while the request stays armed, and multishot recv requires provided buffers. IORING_OP_POLL_ADD accepts 32-bit epoll flags since 5.9. IORING_OP_TIMEOUT (5.4) fires on expiry or on a completion count, on CLOCK_MONOTONIC unless REALTIME/BOOTTIME (5.15), and since 5.11 io_uring_enter(2) itself takes a wait timeout. ASYNC_CANCEL answers 0, -ENOENT or -EALREADY; the 5.19 flags cancel all matches, by fd or everything.

## Facts

1. [[f-os-io-uring-multishot-accept]]
2. [[f-os-io-uring-cqe-f-more]]
3. [[f-os-io-uring-multishot-recv]]
4. [[f-os-io-uring-poll-32bit-flags]]
5. [[f-os-io-uring-timeout-op]]
6. [[f-os-io-uring-timeout-realtime-clock]]
7. [[f-os-io-uring-enter-ext-arg-timeout]]
8. [[f-os-io-uring-async-cancel-results]]
9. [[f-os-io-uring-cancel-all-fd-any]]
