---
id: f-os-io-uring-register-reduces-overhead
type: fact
domain: os
title: Registering files and buffers cuts per-I/O overhead
summary: Registering files or user buffers through io_uring_register(2) pins the
  kernel-side references once, so each request skips the per-operation fget/fput
  and page pinning.
claim: io_uring_register(2) lets the kernel keep long-term references to files 
  and mappings of buffers, reducing per-I/O cost.
kind: mechanism
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- регистрация файлов и буферов
- io_uring_register
- fixed files
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

io_uring_register(2) lets the kernel keep long-term references to files and mappings of buffers, reducing per-I/O cost. [@src-man-io-uring-register-2 гл. 2 "allows the kernel to take long term references to internal data structures or create long term mappings of application memory, greatly reducing per-I/O overhead"]

## Why

Reference counting on shared file tables and page pinning dominate the cost of small I/Os.
