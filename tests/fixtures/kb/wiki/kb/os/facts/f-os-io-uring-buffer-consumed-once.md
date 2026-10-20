---
id: f-os-io-uring-buffer-consumed-once
type: fact
domain: os
title: A selected buffer leaves the pool until re-provided
summary: 'Buffer selection is consuming: after a completion the application owns the
  buffer and must re-provide it (IORING_OP_PROVIDE_BUFFERS or a buffer ring) before
  the kernel can hand it out again.'
claim: Once a provided buffer is used by a request it is gone from the kernel 
  pool until the application provides it again.
kind: pitfall
confidence: sourced
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- повторное предоставление буфера
- буфер используется один раз
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-provided-buffers
  refines:
  - f-os-io-uring-provide-buffers-pool
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Once a provided buffer is used by a request it is gone from the kernel pool until the application provides it again. [@src-man-io-uring-enter-2 гл. 2 "Once a buffer has been used, it is no longer available in the kernel pool"]

## Why

The kernel cannot know when the application finished reading the data.
