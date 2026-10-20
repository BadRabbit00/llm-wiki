---
id: f-os-io-uring-rings-in-shared-memory
type: fact
domain: os
title: Requests and completions live in memory shared with the kernel
summary: Instead of a system call per operation, io_uring places requests in a 
  shared submission ring and reads completions from a shared completion ring.
claim: User space and the kernel exchange io_uring requests and completions 
  through two ring buffers in shared memory.
kind: mechanism
confidence: inferred
scopes:
- layer:kernel
- tech:io-uring
aliases:
- разделяемые кольца
- память, общая с ядром
sources:
- src-man-io-uring-7
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

User space and the kernel exchange io_uring requests and completions through two ring buffers in shared memory. [@src-man-io-uring-7]

## Caveats

The ring memory is obtained with mmap(2) on the ring file descriptor.
