---
id: f-os-io-uring-single-mmap-feature
type: fact
domain: os
title: IORING_FEAT_SINGLE_MMAP maps SQ and CQ rings together
summary: Since Linux 5.4 the kernel reports IORING_FEAT_SINGLE_MMAP so that one 
  mmap(2) covers both the SQ and CQ ring, reducing the mappings from three to 
  two.
claim: With IORING_FEAT_SINGLE_MMAP the SQ and CQ rings share one mmap call; the
  SQE array is still mapped separately.
kind: api
confidence: sourced
valid_for: linux>=5.4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- единый mmap колец
- IORING_FEAT_SINGLE_MMAP
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-ring-model
  refines:
  - f-os-io-uring-mmap-offsets
  replaces:
  - f-os-io-uring-three-mmaps
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_FEAT_SINGLE_MMAP the SQ and CQ rings share one mmap call; the SQE array is still mapped separately. [@src-man-io-uring-setup-2 гл. 2 "the two SQ and CQ rings can be mapped with a single mmap(2) call. The SQEs must still be allocated separately"]

## Why

Fewer mappings mean fewer VMAs and a simpler setup path; liburing checks the feature bit for you.
