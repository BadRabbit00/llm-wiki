---
id: f-os-io-uring-defer-taskrun
type: fact
domain: os
title: IORING_SETUP_DEFER_TASKRUN defers completion work to enter
summary: With IORING_SETUP_DEFER_TASKRUN (Linux 6.1) io_uring no longer runs 
  completion work at every syscall return but batches it into io_uring_enter(2) 
  GETEVENTS calls; it requires SINGLE_ISSUER.
claim: IORING_SETUP_DEFER_TASKRUN defers completion processing until 
  io_uring_enter with IORING_ENTER_GETEVENTS.
kind: api
confidence: sourced
valid_for: linux>=6.1
scopes:
- layer:kernel
- tech:io-uring
aliases:
- отложенная обработка завершений
- IORING_SETUP_DEFER_TASKRUN
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-setup-flags
  applies_with:
  - id: f-os-io-uring-single-issuer
    w: 0.9
    note: DEFER_TASKRUN is rejected without SINGLE_ISSUER
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

IORING_SETUP_DEFER_TASKRUN defers completion processing until io_uring_enter with IORING_ENTER_GETEVENTS. [@src-man-io-uring-setup-2 гл. 2 "This flag requires the IORING_SETUP_SINGLE_ISSUER flag to be set, and also enforces that the call to io_uring_enter(2) is called from the same thread that submitted requests"]

## Why

Batching task work avoids interrupting the application and improves cache locality of completions.
