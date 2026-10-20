---
id: top-os-io-uring-setup-flags
type: topic
domain: os
title: io_uring setup flags and polling modes
summary: 'IORING_SETUP_* flags that change how a ring is driven: IOPOLL, SQPOLL and
  its wakeup protocol, CLAMP, R_DISABLED, SINGLE_ISSUER, DEFER_TASKRUN; the io_uring_disabled
  sysctl.'
priority: 4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- флаги io_uring_setup
- режимы поллинга
- SQPOLL и IOPOLL
relations:
  builds_on:
  - top-os-io-uring-ring-model
  applies_with:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

io_uring_setup(2) flags select how the ring is driven. IOPOLL busy-polls the device for completions and only works with O_DIRECT files. SQPOLL starts a kernel thread that consumes SQEs without syscalls; after sq_thread_idle ms it sleeps and must be woken through io_uring_enter(2), and since 5.11 it accepts ordinary file descriptors. CLAMP bounds oversized rings instead of failing, R_DISABLED starts the ring disabled so restrictions can be installed, and SINGLE_ISSUER plus DEFER_TASKRUN (6.0, 6.1) trade generality for a cheaper single-thread submission and batched completion processing. Since 6.6 the sysctl kernel.io_uring_disabled can restrict ring creation to privileged processes or switch io_uring off.

## Facts

1. [[f-os-io-uring-iopoll-busy-wait]]
2. [[f-os-io-uring-iopoll-requires-o-direct]]
3. [[f-os-io-uring-sqpoll-kernel-thread]]
4. [[f-os-io-uring-sqpoll-idle-wakeup]]
5. [[f-os-io-uring-enter-sq-wakeup]]
6. [[f-os-io-uring-sqpoll-nonfixed-files]]
7. [[f-os-io-uring-attach-wq]]
8. [[f-os-io-uring-clamp-flag]]
9. [[f-os-io-uring-r-disabled]]
10. [[f-os-io-uring-single-issuer]]
11. [[f-os-io-uring-defer-taskrun]]
12. [[f-os-io-uring-disabled-sysctl]]

## Open questions

- [[q-os-io-uring-sqpoll-dedicated-core]]
