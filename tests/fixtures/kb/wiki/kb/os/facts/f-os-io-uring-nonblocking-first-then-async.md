---
id: f-os-io-uring-nonblocking-first-then-async
type: fact
domain: os
title: Requests are tried non-blocking before going async
summary: The default issue path attempts the operation inline without blocking 
  and punts it to async workers only when that fails; IOSQE_ASYNC (Linux 5.6) 
  skips the inline attempt for requests known to block.
claim: io_uring first tries to issue an SQE non-blocking and only on failure 
  executes it asynchronously; IOSQE_ASYNC forces async from the start.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IOSQE_ASYNC
- неблокирующая попытка
- punt в async
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring first tries to issue an SQE non-blocking and only on failure executes it asynchronously; IOSQE_ASYNC forces async from the start. [@src-man-io-uring-enter-2 гл. 2 "Normal operation for io_uring is to try and issue an sqe as non-blocking first, and if that fails, execute it in an async manner"]

## Why

Inline completion avoids a thread hop for data already in the page cache or a ready socket.
