---
id: f-os-liburing-cqe-seen
type: fact
domain: os
title: 'Step 6: io_uring_cqe_seen frees the CQE slot'
summary: After reading a completion the application calls io_uring_cqe_seen(3) 
  (or io_uring_cq_advance(3) for a batch) to advance the CQ head; forgetting it 
  eventually fills the CQ.
claim: Every consumed CQE must be marked with io_uring_cqe_seen(3) so its ring 
  slot can be reused.
kind: step
confidence: sourced
scopes:
- layer:kernel
- tech:io-uring
aliases:
- пометить CQE прочитанным
- io_uring_cqe_seen
sources:
- src-liburing-man-3
relations:
  about:
  - top-os-io-uring-submission
  - tech-liburing
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

Every consumed CQE must be marked with io_uring_cqe_seen(3) so its ring slot can be reused. [@src-liburing-man-3 гл. 3 "Completions must be marked as seen, so their slot can get reused"]

## Why

The CQ head lives in shared memory; only the application may move it.
