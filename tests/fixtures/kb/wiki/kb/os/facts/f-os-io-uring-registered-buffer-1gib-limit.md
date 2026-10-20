---
id: f-os-io-uring-registered-buffer-1gib-limit
type: fact
domain: os
title: A registered buffer may not exceed 1 GiB
summary: io_uring_register(2) rejects a single iovec larger than 1 GiB when 
  registering fixed buffers; use several registered buffers for larger pools.
claim: Each buffer registered with IORING_REGISTER_BUFFERS is limited to 1 GiB 
  in size.
kind: number
confidence: sourced
valid_for: linux>=5.1
value: '1'
unit: GiB
scopes:
- layer:kernel
- tech:io-uring
aliases:
- максимальный размер registered buffer
- 1 ГиБ на буфер
sources:
- src-man-io-uring-register-2
relations:
  about:
  - top-os-io-uring-registration
  related:
  - f-os-io-uring-register-buffers-memlock
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Each buffer registered with IORING_REGISTER_BUFFERS is limited to 1 GiB in size. [@src-man-io-uring-register-2 гл. 2 "there is a size limit of 1GiB per buffer"]

## Why

The pinning bookkeeping is per buffer and bounded by the kernel.
