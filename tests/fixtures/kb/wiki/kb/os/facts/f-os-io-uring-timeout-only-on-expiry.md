---
id: f-os-io-uring-timeout-only-on-expiry
type: fact
domain: os
title: A timeout request completes only when it expires
summary: The belief that the completion count of a timeout request is ignored 
  and the request is a pure timer.
claim: IORING_OP_TIMEOUT completes only when its timespec expires; other 
  completions never finish it early.
kind: api
confidence: contested
valid_for: linux>=5.4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- таймаут только по истечении
- таймер без счётчика событий
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
  contradicts:
  - f-os-io-uring-timeout-op
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_TIMEOUT completes only when its timespec expires; other completions never finish it early. [@src-man-io-uring-enter-2]

## Caveats

Contradicts [[f-os-io-uring-timeout-op]].
