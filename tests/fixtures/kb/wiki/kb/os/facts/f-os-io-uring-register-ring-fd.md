---
id: f-os-io-uring-register-ring-fd
type: fact
domain: os
title: IORING_REGISTER_RING_FDS makes io_uring_enter cheaper
summary: IORING_REGISTER_RING_FDS (Linux 5.18) registers the ring's own 
  descriptor; io_uring_enter(2) with IORING_ENTER_REGISTERED_RING then skips the
  file-table reference, which matters in threaded programs.
claim: Registering the ring fd with IORING_REGISTER_RING_FDS removes the fd 
  reference grab from every io_uring_enter.
kind: api
confidence: sourced
valid_for: linux>=5.18
scopes:
- layer:kernel
- tech:io-uring
aliases:
- регистрация дескриптора кольца
- IORING_REGISTER_RING_FDS
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Registering the ring fd with IORING_REGISTER_RING_FDS removes the fd reference grab from every io_uring_enter. [@src-man-io-uring-register-2 гл. 2 "This reduces the overhead of the io_uring_enter(2) system call"]

## Why

In a threaded process the file table is shared, so each fget/fput is an atomic on a contended line.

## Caveats

liburing registers the ring fd per thread; a ring fd registered in one task is not usable from another.
