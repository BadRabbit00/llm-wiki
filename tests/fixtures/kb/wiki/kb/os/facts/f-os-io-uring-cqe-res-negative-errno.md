---
id: f-os-io-uring-cqe-res-negative-errno
type: fact
domain: os
title: A CQE reports failure as negative errno in res
summary: 'io_uring completion entries return the syscall-style result in `res`: a
  byte count or 0 on success, and -errno (for example -EBADF) when the request failed.'
claim: The CQE res field holds the operation result or a negative errno value on
  failure.
kind: convention
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- код ошибки CQE
- отрицательный errno
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-ring-model
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

The CQE res field holds the operation result or a negative errno value on failure. [@src-man-io-uring-enter-2 гл. 2 "res is the operation-specific result, but io_uring-specific errors (e.g. flags or opcode invalid) are returned through this field"]

## Why

Unlike read(2), there is no errno variable per request; the sign of res carries the error.
