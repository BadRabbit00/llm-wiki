---
id: f-os-io-uring-timeout-op
type: fact
domain: os
title: IORING_OP_TIMEOUT fires on time or on a completion count
summary: A timeout request (Linux 5.4) takes a struct timespec and an optional 
  completion count in `off`; whichever condition is met first completes it and 
  wakes CQ waiters.
claim: IORING_OP_TIMEOUT completes when its timespec expires or when the given 
  number of completions has been posted.
kind: api
confidence: sourced
valid_for: linux>=5.4
scopes:
- layer:kernel
- tech:io-uring
aliases:
- таймаут io_uring
- IORING_OP_TIMEOUT
sources:
- src-man-io-uring-enter-2
relations:
  about:
  - top-os-io-uring-multishot-timeouts-cancel
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_OP_TIMEOUT completes when its timespec expires or when the given number of completions has been posted. [@src-man-io-uring-enter-2 гл. 2 "A timeout condition is met when either the specified timeout expires, or the specified number of events have completed"]

## Why

It lets a wait loop bound its latency without a separate timer fd.

## Caveats

Absolute timeouts need IORING_TIMEOUT_ABS; the default clock is CLOCK_MONOTONIC.
