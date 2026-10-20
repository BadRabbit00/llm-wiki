---
id: f-os-io-uring-prep-read-since-5-6
type: fact
domain: os
title: Non-vectored IORING_OP_READ exists since 5.6
summary: The simple read/write opcodes (IORING_OP_READ, IORING_OP_WRITE) behind 
  io_uring_prep_read(3) and io_uring_prep_write(3) exist since Linux 5.6; 
  earlier kernels only offer the readv/writev variants.
claim: io_uring_prep_read(3) prepares a non-vectored IORING_OP_READ, available 
  since Linux 5.6.
kind: api
confidence: sourced
valid_for: linux>=5.6
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io_uring_prep_read
- IORING_OP_READ
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  replaces:
  - f-os-io-uring-readv-only-before-5-6
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_prep_read(3) prepares a non-vectored IORING_OP_READ, available since Linux 5.6. [@src-liburing-man-3 гл. 3 "This function is available since 5.6"]

## Why

A single buffer avoids the iovec indirection for the common one-buffer case.
