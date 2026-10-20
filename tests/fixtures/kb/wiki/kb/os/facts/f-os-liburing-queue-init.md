---
id: f-os-liburing-queue-init
type: fact
domain: os
title: 'Step 1: io_uring_queue_init sets up and maps the ring'
summary: liburing's io_uring_queue_init(3) performs io_uring_setup(2) for at 
  least `entries` entries and mmaps the resulting fd so the struct io_uring is 
  ready to use.
claim: io_uring_queue_init(3) calls io_uring_setup(2) and maps the rings into a 
  struct io_uring.
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- инициализация кольца liburing
- io_uring_queue_init
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  precedes:
  - f-os-liburing-get-sqe
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_queue_init(3) calls io_uring_setup(2) and maps the rings into a struct io_uring. [@src-liburing-man-3 гл. 3 "executes the io_uring_setup(2) system call to initialize the submission and completion queues in the kernel with at least entries entries"]

## Why

It hides the feature probing and the two or three mmap calls needed for the raw interface.

## Example

```c
struct io_uring ring;
int rc = io_uring_queue_init(256, &ring, 0);
```
