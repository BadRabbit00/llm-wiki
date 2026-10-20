---
id: f-os-io-uring-registered-buffers-pageable
type: fact
domain: os
title: Registered buffers are ordinary pageable memory
summary: The belief that registering buffers only records their addresses and 
  leaves the pages unpinned and unaccounted.
claim: Buffers registered with IORING_REGISTER_BUFFERS stay pageable and are not
  charged to RLIMIT_MEMLOCK.
kind: constraint
confidence: contested
scopes:
- layer:kernel
- tech:io-uring
aliases:
- registered buffers не закрепляются
- буферы без memlock
sources:
- src-man-io-uring-register-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-register-buffers-memlock
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Buffers registered with IORING_REGISTER_BUFFERS stay pageable and are not charged to RLIMIT_MEMLOCK. [@src-man-io-uring-register-2]

## Caveats

Contradicts [[f-os-io-uring-register-buffers-memlock]].
