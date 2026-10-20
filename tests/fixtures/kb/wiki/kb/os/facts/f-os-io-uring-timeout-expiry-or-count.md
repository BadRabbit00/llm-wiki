---
id: f-os-io-uring-timeout-expiry-or-count
type: fact
domain: os
title: A timeout request completes on expiry or after N completions
summary: A timeout SQE (Linux 5.4) carries a timespec and an optional completion
  count; the first of the two conditions completes the request.
claim: IORING_OP_TIMEOUT finishes either when its time elapses or when the 
  configured number of other completions has been posted.
kind: api
confidence: inferred
valid_for: linux>=5.4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- таймаут по времени или числу событий
- IORING_OP_TIMEOUT
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - tech-io-uring
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_TIMEOUT finishes either when its time elapses or when the configured number of other completions has been posted. [@src-man-io-uring-enter-2]

## Caveats

A count of zero turns the request into a pure timer.
