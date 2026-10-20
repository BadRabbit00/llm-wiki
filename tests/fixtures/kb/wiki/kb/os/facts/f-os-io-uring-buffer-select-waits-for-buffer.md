---
id: f-os-io-uring-buffer-select-waits-for-buffer
type: fact
domain: os
title: A request waits when the buffer group is empty
summary: The belief that an exhausted provided-buffer group makes the kernel 
  park the request until the application provides more buffers.
claim: A request with IOSQE_BUFFER_SELECT waits until a buffer is provided if 
  its group is empty.
kind: pitfall
confidence: contested
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- ожидание буфера
- BUFFER_SELECT при пустой группе
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-buffer-select-enobufs
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A request with IOSQE_BUFFER_SELECT waits until a buffer is provided if its group is empty. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-buffer-select-enobufs]].
