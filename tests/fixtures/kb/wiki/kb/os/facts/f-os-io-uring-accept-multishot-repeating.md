---
id: f-os-io-uring-accept-multishot-repeating
type: fact
domain: os
title: A multishot accept keeps accepting connections
summary: io_uring multishot accept (Linux 5.19) arms a single request that stays
  active and emits a CQE per accepted connection until cancelled.
claim: One multishot accept submission repeatedly posts a completion for each 
  new connection without resubmission.
kind: api
confidence: inferred
valid_for: linux>=5.19
scopes:
- layer:kernel
- tech:io-uring
aliases:
- повторяющийся accept
- accept multishot
sources:
- src-liburing-man-3
relations:
  about:
  - tech-liburing
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

One multishot accept submission repeatedly posts a completion for each new connection without resubmission. [@src-liburing-man-3]

## Caveats

Each completion carries the new socket's descriptor in res, as a plain accept would.
