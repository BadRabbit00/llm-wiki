---
id: f-os-io-uring-enter-always-blocks
type: fact
domain: os
title: io_uring_enter always blocks until all submissions complete
summary: The belief that io_uring_enter(2) is a synchronous call that returns 
  only after all submitted requests finish, regardless of flags.
claim: io_uring_enter(2) always blocks until every SQE it submitted has 
  completed.
kind: api
confidence: contested
valid_for: linux>=5.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- io_uring_enter блокирует до завершения
- синхронный io_uring_enter
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-enter-getevents
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_enter(2) always blocks until every SQE it submitted has completed. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-enter-getevents]].
