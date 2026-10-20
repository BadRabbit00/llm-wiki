---
id: f-os-io-uring-three-mmaps
type: fact
domain: os
title: Ring setup needs three mmap calls (before 5.4)
summary: Before IORING_FEAT_SINGLE_MMAP (Linux 5.4) the SQ ring and CQ ring were
  separate mappings, so a ring needed three mmap(2) calls.
claim: 'Mapping an io_uring instance takes three mmap calls: the SQ ring, the CQ ring
  and the SQE array.'
kind: api
confidence: sourced
valid_for: linux>=5.1, linux<5.4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- три вызова mmap
- раздельное отображение колец
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Mapping an io_uring instance takes three mmap calls: the SQ ring, the CQ ring and the SQE array. [@src-man-io-uring-setup-2 гл. 2 "This brings the necessary mmap(2) calls down from three to two"]

## Caveats

The three-mapping layout is still accepted by newer kernels, which is why liburing probes the feature bit.
