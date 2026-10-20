---
id: f-os-io-uring-setup-returns-fd
type: fact
domain: os
title: io_uring_setup creates the rings and returns a file descriptor
summary: The io_uring_setup(2) system call allocates the submission and 
  completion queues for at least `entries` entries and returns the fd used for 
  mmap and io_uring_enter.
claim: io_uring_setup(2) creates an SQ and a CQ with at least the requested 
  entries and returns a file descriptor.
kind: api
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- создание кольца io_uring
- io_uring_setup
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_setup(2) creates an SQ and a CQ with at least the requested entries and returns a file descriptor. [@src-man-io-uring-setup-2 гл. 2 "sets up a submission queue (SQ) and completion queue (CQ) with at least entries entries, and returns a file descriptor"]

## Why

The fd is the handle for mmap(2) of the ring memory, io_uring_enter(2) and io_uring_register(2).

## Example

```c
struct io_uring_params p = {0};
int fd = io_uring_setup(256, &p);
```
