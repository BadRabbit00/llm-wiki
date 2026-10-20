---
id: f-os-io-uring-sqpoll-kernel-thread
type: fact
domain: os
title: IORING_SETUP_SQPOLL starts a kernel submission thread
summary: With IORING_SETUP_SQPOLL the kernel runs a dedicated thread that picks 
  up SQEs from the ring, so the application can submit I/O without calling 
  io_uring_enter(2).
claim: IORING_SETUP_SQPOLL creates a kernel thread that polls the submission 
  queue on behalf of the application.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- поток SQPOLL
- отправка без системных вызовов
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_SQPOLL creates a kernel thread that polls the submission queue on behalf of the application. [@src-man-io-uring-setup-2 гл. 2 "a kernel thread is created to perform submission queue polling"]

## Why

Removing the submission syscall matters for sub-microsecond latency and very high IOPS.

## Caveats

The thread burns a CPU while active; see the idle timeout and wakeup protocol.
