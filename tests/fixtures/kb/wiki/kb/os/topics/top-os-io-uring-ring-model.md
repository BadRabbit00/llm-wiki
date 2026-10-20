---
id: top-os-io-uring-ring-model
type: topic
domain: os
title: 'io_uring ring model: SQ, CQ, SQE and CQE'
summary: 'How io_uring exchanges requests and completions through shared rings: setup,
  mmap layout, entry sizes, user_data and result codes.'
priority: 4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- модель колец io_uring
- очередь отправки и завершения
- SQE и CQE
relations:
  applies_with:
  - top-os-io-uring-submission
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Digest

io_uring is a Linux asynchronous I/O interface built on two ring buffers shared between user space and the kernel: the submission queue (SQ) of 64-byte SQEs and the completion queue (CQ) of CQEs. io_uring_setup(2) creates both for at least the requested entries (at most 32768 since 5.4) and returns an fd; the application maps the SQ ring, CQ ring and SQE array through fixed mmap offsets, or two mappings with IORING_FEAT_SINGLE_MMAP. A 64-bit user_data token travels unchanged from SQE to CQE, and a CQE carries the result or a negative errno in res; IORING_SETUP_CQSIZE sizes the CQ independently.

## Facts

1. [[f-os-io-uring-shared-rings]]
2. [[f-os-io-uring-setup-returns-fd]]
3. [[f-os-io-uring-max-entries-32768]]
4. [[f-os-io-uring-mmap-offsets]]
5. [[f-os-io-uring-single-mmap-feature]]
6. [[f-os-io-uring-sqe-64-bytes]]
7. [[f-os-io-uring-user-data-roundtrip]]
8. [[f-os-io-uring-cqe-res-negative-errno]]
9. [[f-os-io-uring-cqsize-flag]]
