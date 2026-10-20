---
id: f-os-io-uring-mmap-offsets
type: fact
domain: os
title: Ring memory is mapped with fixed mmap offsets
summary: After io_uring_setup(2) the application maps three regions of the ring 
  fd using the offset constants IORING_OFF_SQ_RING (0), IORING_OFF_CQ_RING 
  (0x8000000) and IORING_OFF_SQES (0x10000000).
claim: The SQ ring, CQ ring and SQE array are mapped with mmap offsets 
  IORING_OFF_SQ_RING, IORING_OFF_CQ_RING and IORING_OFF_SQES.
kind: api
confidence: inferred
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отображение колец mmap
- IORING_OFF_SQES
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

The SQ ring, CQ ring and SQE array are mapped with mmap offsets IORING_OFF_SQ_RING, IORING_OFF_CQ_RING and IORING_OFF_SQES. [@src-man-io-uring-setup-2]

## Why

Sizes and field offsets for each region come from struct io_uring_params filled by io_uring_setup(2).
