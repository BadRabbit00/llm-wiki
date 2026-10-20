---
id: q-os-io-uring-sqpoll-dedicated-core
type: question
domain: os
title: Is SQPOLL worth a dedicated core for our network services?
summary: 'Open: SQPOLL removes submission syscalls but pins a kernel thread to a core;
  we have no measurement of the gain versus batching with plain io_uring_enter at
  our request sizes.'
priority: 2
scopes:
- layer:kernel
- tech:io-uring
aliases:
- нужен ли SQPOLL
- SQPOLL и выделенное ядро
relations:
  about:
  - top-os-io-uring-setup-flags
  answered_by: []
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Context

SQPOLL ([[f-os-io-uring-sqpoll-kernel-thread]]) trades a busy core for zero submission syscalls, and sleeps after `sq_thread_idle` ([[f-os-io-uring-sqpoll-idle-wakeup]]). Batched submission with IORING_ENTER_GETEVENTS may already amortise the syscall.

## What would answer it

A benchmark on our 24-core hosts at 64-byte and 4 KiB requests: p99 latency and CPU per request with and without SQPOLL.
