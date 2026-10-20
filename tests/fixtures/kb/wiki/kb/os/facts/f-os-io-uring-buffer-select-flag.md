---
id: f-os-io-uring-buffer-select-flag
type: fact
domain: os
title: IOSQE_BUFFER_SELECT picks a provided buffer at readiness
summary: A request flagged IOSQE_BUFFER_SELECT names a buffer group in buf_group
  instead of a user buffer; the kernel selects a buffer at the moment data is 
  available and reports its ID in the CQE flags.
claim: IOSQE_BUFFER_SELECT makes a read or receive take a buffer from the 
  provided group when it is ready for data.
kind: api
confidence: sourced
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- выбор буфера ядром
- IOSQE_BUFFER_SELECT
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-provided-buffers
  applies_with:
  - id: f-os-io-uring-provide-buffers-pool
    w: 0.9
    note: the group must be provided before the request can select from it
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IOSQE_BUFFER_SELECT makes a read or receive take a buffer from the provided group when it is ready for data. [@src-man-io-uring-enter-2 гл. 2 "io_uring will grab a buffer from this pool when the request is ready to receive or read data"]

## Why

The CQE carries IORING_CQE_F_BUFFER and the buffer ID in the upper bits, so the application knows which buffer was used.
