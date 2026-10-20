---
id: top-os-io-uring-submission
type: topic
domain: os
title: Submitting and reaping with io_uring_enter and liburing
summary: 'The submit/complete loop: io_uring_enter(2) semantics, completion ordering
  and overflow, and the six-step liburing cycle from queue_init to cqe_seen.'
priority: 5
scopes:
- layer:kernel
- tech:io-uring
- tech:liburing
aliases:
- отправка и получение завершений
- цикл liburing
- io_uring_enter
relations:
  builds_on:
  - top-os-io-uring-ring-model
  applies_with:
  - top-os-io-uring-linking
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

A single io_uring_enter(2) call submits up to to_submit SQEs and, with IORING_ENTER_GETEVENTS, waits for min_complete completions. Requests start in submission order but complete in any order; since 5.5 a full CQ buffers overflow instead of dropping it, and IOSQE_CQE_SKIP_SUCCESS (5.17) suppresses successful completions. Requests are tried non-blocking first and punted to native io-wq workers (5.12) only if needed; FAST_POLL (5.7) waits for readiness without a thread. With liburing the loop is: io_uring_queue_init, io_uring_get_sqe, io_uring_prep_* plus io_uring_sqe_set_data, io_uring_submit, io_uring_wait_cqe, io_uring_cqe_seen.

## Facts

1. [[f-os-io-uring-enter-submit-and-wait]]
2. [[f-os-io-uring-enter-getevents]]
3. [[f-os-io-uring-completions-unordered]]
4. [[f-os-io-uring-nodrop-overflow]]
5. [[f-os-io-uring-cqe-skip-success]]
6. [[f-os-io-uring-nonblocking-first-then-async]]
7. [[f-os-io-uring-fast-poll]]
8. [[f-os-io-uring-native-workers]]
9. [[f-os-io-uring-prep-read-since-5-6]]
10. [[f-os-liburing-queue-init]]
11. [[f-os-liburing-get-sqe]]
12. [[f-os-liburing-prep-and-set-data]]
13. [[f-os-liburing-submit]]
14. [[f-os-liburing-submit-and-wait]]
15. [[f-os-liburing-wait-cqe]]
16. [[f-os-liburing-cqe-seen]]
