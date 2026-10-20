---
id: f-os-io-uring-sqe-64-bytes
type: fact
domain: os
title: An SQE is 64 bytes by default
summary: struct io_uring_sqe occupies 64 bytes on the default ring; 
  IORING_SETUP_SQE128 (Linux 5.19) doubles it for commands such as NVMe 
  passthrough.
claim: A submission queue entry is 64 bytes; IORING_SETUP_SQE128 switches the 
  ring to 128-byte entries.
kind: number
confidence: sourced
valid_for: linux>=5.1
value: '64'
unit: bytes
scopes:
- layer:kernel
- tech:io-uring
aliases:
- размер SQE
- IORING_SETUP_SQE128
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

A submission queue entry is 64 bytes; IORING_SETUP_SQE128 switches the ring to 128-byte entries. [@src-man-io-uring-setup-2 гл. 2 "io_uring will use 128-byte SQEs rather than the normal 64-byte sized variant"]

## Why

A fixed-size entry lets the ring be indexed arithmetically; one cache line per SQE on x86.
