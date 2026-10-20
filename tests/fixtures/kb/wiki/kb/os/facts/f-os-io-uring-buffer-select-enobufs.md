---
id: f-os-io-uring-buffer-select-enobufs
type: fact
domain: os
title: An empty buffer group fails the request with -ENOBUFS
summary: If the provided buffer group is exhausted when a selecting read or 
  receive becomes ready, io_uring completes the request with -ENOBUFS instead of
  waiting for a buffer.
claim: A request with IOSQE_BUFFER_SELECT fails with -ENOBUFS when its buffer 
  group has no buffers left.
kind: pitfall
confidence: sourced
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- ENOBUFS
- закончились буферы
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-provided-buffers
  refines:
  - f-os-io-uring-buffer-select-flag
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

A request with IOSQE_BUFFER_SELECT fails with -ENOBUFS when its buffer group has no buffers left. [@src-man-io-uring-enter-2 гл. 2 "If no buffers are available and this flag is set, then the request will fail with -ENOBUFS as the error code"]

## Why

The kernel never blocks a request on user-provided memory; the application must replenish and resubmit.
