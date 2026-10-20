---
id: top-os-io-uring-provided-buffers
type: topic
domain: os
title: Provided buffers and buffer rings
summary: 'Letting the kernel pick the buffer at readiness: IORING_OP_PROVIDE_BUFFERS,
  IOSQE_BUFFER_SELECT, -ENOBUFS, single-use buffers and the 5.19 buffer ring.'
priority: 3
scopes:
- layer:kernel
- tech:io-uring
aliases:
- предоставленные буферы
- buffer select
- кольцо буферов
relations:
  builds_on:
  - top-os-io-uring-registration
  applies_with:
  - top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

Provided buffers decouple buffer memory from pending requests. The application gives the kernel a group of buffers (IORING_OP_PROVIDE_BUFFERS, 5.7, or a registered buffer ring since 5.19) and submits reads or receives with IOSQE_BUFFER_SELECT; the kernel takes a buffer only when data is ready and reports its ID in the CQE flags. An exhausted group fails the request with -ENOBUFS, and every selected buffer leaves the pool until the application provides it again.

## Facts

1. [[f-os-io-uring-provide-buffers-pool]]
2. [[f-os-io-uring-buffer-select-flag]]
3. [[f-os-io-uring-buffer-select-enobufs]]
4. [[f-os-io-uring-buffer-consumed-once]]
5. [[f-os-io-uring-buf-ring]]
