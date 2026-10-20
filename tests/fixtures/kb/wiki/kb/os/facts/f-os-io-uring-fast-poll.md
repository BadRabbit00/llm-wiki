---
id: f-os-io-uring-fast-poll
type: fact
domain: os
title: IORING_FEAT_FAST_POLL waits for readiness without a thread
summary: Since Linux 5.7 (IORING_FEAT_FAST_POLL) io_uring arms an internal poll 
  for requests that cannot proceed yet and issues them when the file becomes 
  ready, so waiting requests cost no worker thread.
claim: With IORING_FEAT_FAST_POLL a read or write on a file that is not ready 
  waits via internal poll instead of being punted to an async thread.
kind: mechanism
confidence: sourced
valid_for: linux>=5.7
scopes:
- layer:kernel
- tech:io-uring
aliases:
- IORING_FEAT_FAST_POLL
- внутренний poll
- без async-потока
sources:
- src-man-io-uring-setup-2
relations:
  about:
  - top-os-io-uring-submission
  related:
  - f-os-io-uring-nonblocking-first-then-async
status: draft
sensitivity: public
created: '2026-10-20'
updated: '2026-10-20'
---

## Claim

With IORING_FEAT_FAST_POLL a read or write on a file that is not ready waits via internal poll instead of being punted to an async thread. [@src-man-io-uring-setup-2 гл. 2 "no longer need to be punted to an async thread for handling, instead they will begin operation when the file is ready"]

## Why

Thousands of idle sockets each holding a worker thread would not scale.
