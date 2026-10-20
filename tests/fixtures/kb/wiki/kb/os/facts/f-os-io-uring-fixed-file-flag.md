---
id: f-os-io-uring-fixed-file-flag
type: fact
domain: os
title: IOSQE_FIXED_FILE makes fd an index into registered files
summary: Setting IOSQE_FIXED_FILE (Linux 5.1) reinterprets sqe->fd as a slot in 
  the table registered via IORING_REGISTER_FILES; commands that do not support 
  fixed files fail with -EBADF.
claim: With IOSQE_FIXED_FILE the SQE fd is an index into the registered file 
  array; unsupported opcodes return -EBADF.
kind: api
confidence: sourced
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- fixed file
- IOSQE_FIXED_FILE
- индекс вместо дескриптора
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-registration
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IOSQE_FIXED_FILE the SQE fd is an index into the registered file array; unsupported opcodes return -EBADF. [@src-man-io-uring-enter-2 гл. 2 "fd is an index into the files array registered with the io_uring instance"]

## Why

The index avoids the file-table lookup and reference churn on every request.

## Caveats

Before Linux 5.11 SQPOLL rings required fixed files for every request.
