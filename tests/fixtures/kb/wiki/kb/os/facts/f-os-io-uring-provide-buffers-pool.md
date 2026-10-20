---
id: f-os-io-uring-provide-buffers-pool
type: fact
domain: os
title: IORING_OP_PROVIDE_BUFFERS hands the kernel a buffer pool
summary: With IORING_OP_PROVIDE_BUFFERS (Linux 5.7) an application pre-provides 
  buffers in a group; a request with IOSQE_BUFFER_SELECT takes one only when 
  data arrives, so idle sockets hold no memory.
claim: IORING_OP_PROVIDE_BUFFERS registers a group of buffers that the kernel 
  picks from when a read or receive becomes ready.
kind: mechanism
confidence: sourced
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- предоставленные буферы
- IORING_OP_PROVIDE_BUFFERS
- buffer group
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-provided-buffers
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_PROVIDE_BUFFERS registers a group of buffers that the kernel picks from when a read or receive becomes ready. [@src-man-io-uring-enter-2 гл. 2 "when the file or socket is ready to read/receive data, a buffer can be selected for the operation"]

## Why

Pre-allocating a buffer per pending recv does not scale to many thousands of mostly idle connections.
