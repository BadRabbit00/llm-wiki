---
id: f-os-io-uring-cqe-res-positive-errno
type: fact
domain: os
title: A failed CQE carries a positive errno
summary: The belief that io_uring reports errors in the completion entry with 
  the same sign as the C errno variable.
claim: On failure the CQE res field holds a positive errno value, exactly like 
  the errno variable.
kind: convention
confidence: contested
scopes:
- layer:kernel
- tech:io-uring
aliases:
- положительный errno в CQE
- знак ошибки в res
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-cqe-res-negative-errno
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

On failure the CQE res field holds a positive errno value, exactly like the errno variable. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-cqe-res-negative-errno]].
