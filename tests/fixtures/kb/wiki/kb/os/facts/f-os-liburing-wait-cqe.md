---
id: f-os-liburing-wait-cqe
type: fact
domain: os
title: 'Step 5: io_uring_wait_cqe blocks for one completion'
summary: io_uring_wait_cqe(3) waits for a completion on the ring (returning 
  immediately if one is already there); its return value reports the wait, not 
  the request result in cqe->res.
claim: io_uring_wait_cqe(3) blocks until a CQE is available and returns 0 with 
  the pointer filled in.
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- ожидание CQE
- io_uring_wait_cqe
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
  precedes:
  - f-os-liburing-cqe-seen
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

io_uring_wait_cqe(3) blocks until a CQE is available and returns 0 with the pointer filled in. [@src-liburing-man-3 гл. 3 "waits for an IO completion from the queue belonging to the ring param, waiting for it if necessary"]

## Why

Use io_uring_peek_cqe(3) for a non-blocking check and io_uring_submit_and_wait(3) to combine steps 4 and 5.
