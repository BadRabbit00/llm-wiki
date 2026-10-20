---
id: f-os-io-uring-buf-ring
type: fact
domain: os
title: Buffer rings replace PROVIDE_BUFFERS requests
summary: A registered buffer ring (IORING_REGISTER_PBUF_RING, Linux 5.19) is a 
  shared memory ring in which the application publishes buffers directly; it is 
  the faster successor of IORING_OP_PROVIDE_BUFFERS.
claim: io_uring_register_buf_ring(3) registers a shared buffer ring so buffers 
  are provided by writing the ring, not by SQEs.
kind: api
confidence: sourced
valid_for: linux>=5.19
scopes:
- layer:kernel
- tech:io-uring
aliases:
- кольцо буферов
- io_uring_register_buf_ring
- IORING_REGISTER_PBUF_RING
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-provided-buffers
  - tech-liburing
  refines:
  - f-os-io-uring-provide-buffers-pool
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_register_buf_ring(3) registers a shared buffer ring so buffers are provided by writing the ring, not by SQEs. [@src-liburing-man-3 гл. 3 "registers a shared buffer ring to be used with provided buffers"]

## Why

Re-providing through SQEs costs a submission per buffer; the ring makes it a store and a tail update.
